# Kinetic DevOps Architecture

## Core Stack (MVP: Minimal Viable Platform)

These three modules form the foundation. No other layers should exist without compelling reason.

### 1. `kinetic_devops/KineticCore.py`
- **Purpose**: Base class for all SDK clients
- **Responsibility**: 
  - Security infrastructure (salt derivation, redaction, wire logging)
  - Header generation (`build_headers()`)
  - Wire logging (`log_wire()`)
  - Config hashing and integrity verification
- **No service logic**: Does not know about BOReader, tax, etc.

### 2. `kinetic_devops/auth.py`
- **Purpose**: Server config and token lifecycle management (keyring-backed)
- **Responsibility**:
  - Session storage and validation
  - Token fetch/refresh (`touch_session()`, `_fetch_token_kinetic()`)
  - Active config resolution (`get_active_config()`)
  - Environment/user prompting (`prompt_for_env()`)
  - Session cleanup
- **No API calls beyond token endpoint**

### 3. `kinetic_devops/base_client.py`
- **Purpose**: Initialize a connected session
- **Responsibility**:
  - Inherit from KineticCore (get security/logging)
  - Store auth config (`self.config`)
  - Generic request execution (`execute_request()`)
  - Session management via KineticConfigManager
- **Usage**: Instantiate once per script; use to access `config` and `execute_request()`

---

## Service Modules (Single Point of Truth)

One dedicated file per service. Internal wrapper layers.

### `kinetic_devops/boreader_service.py`
- **Class**: `BOReaderService`
- **Single Responsibility**: Ice.Lib.BOReaderSvc/GetList endpoint
- **Defensive Design**: Accepts `request_dict` (flexible, not parameter list)
- **No Auth Logic**: Caller provides headers
- **Usage**:
  ```python
  service = BOReaderService(base_url=client.config['url'], 
                            headers=client.build_headers(...))
  result = service.get_list(company='ACME', 
                           request_dict={'serviceNamespace': '...', ...})
  ```

---

## Utilities (Convenience Only)

### `scripts/kinetic_devops_utils.py`
- **Class**: `KineticScriptLogger` (centralized file+console logging)
- **No business logic**: Just logging
- **No service methods**: Callers use service modules directly
- **Lightweight**: ~60 lines, pure utility

---

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│ KineticCore                             │
│ - build_headers()                       │
│ - log_wire()                            │
│ - Security/redaction/hashing            │
└──────────────────▲──────────────────────┘
                   │ inherits
┌──────────────────┴──────────────────────┐
│ KineticBaseClient                       │
│ - __init__(env_nickname, user_id)       │
│ - self.config = {url, token, api_key...}│
│ - execute_request(method, url, payload) │
│ - self.mgr (KineticConfigManager)       │
└──────────────────┬──────────────────────┘
                   │ used by
        ┌──────────┼──────────┐
        │          │          │
        ▼          ▼          ▼
   BOReader   BAQ          Custom
   Service    Service      Service
   (your      (SQL like    (as
   code)      queries)     needed)
```

---

## Workflow Example: Script Using BOReader

```python
from kinetic_devops.base_client import KineticBaseClient
from kinetic_devops.boreader_service import BOReaderService
from kinetic_devops_utils import KineticScriptLogger
from pathlib import Path

# 1. Setup logging
logger = KineticScriptLogger(Path("operation.log"))
logger.section("Fetching Data")

# 2. Init session (prompts interactively: env, user, password, company)
client = KineticBaseClient()
logger.info(f"Connected to {client.config['url']}")

# 3. Create service with config from client
service = BOReaderService(
    base_url=client.config['url'],
    headers=client.build_headers(
        token=client.config['token'],
        api_key=client.config['api_key'],
        company=client.config['company']
    )
)

# 4. Query BOReader
result = service.get_list(
    company=client.config['company'],
    request_dict={
        'serviceNamespace': 'Ice.Lib.SomeSvc',
        'whereClause': "Status = 'Active'",
        'columnList': ['OrderNum', 'OrderDate', 'CustomerID']
    }
)

# 5. Process results
records = result.get('value', [])
logger.info(f"Retrieved {len(records)} records")
for rec in records:
    logger.debug(f"  - {rec}")
```

---

## Design Principles

1. **No Wrapper Wrappers**: If base_client calls a service, don't wrap it again in utils.
2. **Defensive APIs**: Use dict/list for request bodies, not rigid parameter lists.
3. **Single Responsibility**: One service per endpoint file.
4. **Minimal Coupling**: Services don't know about auth; caller provides headers.
5. **Explicit Over Implicit**: No magic config resolution inside services.

---

## When to Add New Services

1. **Create new file**: `kinetic_devops/my_service.py`
2. **Define class**: `MyService` with `__init__(base_url, headers)`
3. **One method per endpoint**: `get_data(company, request_dict)`
4. **Defensive design**: Accept `dict`, return `dict`
5. **No auth logic**: Caller provides headers via `build_headers()`

Example:
```python
# kinetic_devops/my_service.py
class MyService:
    def __init__(self, base_url: str, headers: Dict[str, str]):
        self.base_url = base_url.rstrip('/')
        self.headers = headers.copy()
    
    def do_operation(self, company: str, request_dict: Dict) -> Dict:
        endpoint = f"{self.base_url}/api/v2/..."
        resp = requests.post(endpoint, json=request_dict, headers=self.headers)
        resp.raise_for_status()
        return resp.json()
```

---

## FAQ

**Q: Should service methods go in base_client or separate files?**  
A: Separate files. base_client is for session init and generic requests. Services are single-purpose.

**Q: What if a service needs auth?**  
A: Caller passes headers (from `client.build_headers()`). Service doesn't know about tokens.

**Q: Can services call other services?**  
A: Yes, but only for composition. Keep dependency chains short.

**Q: What about logging inside services?**  
A: Services can log errors. Complex logging is caller responsibility (use KineticScriptLogger).

**Q: Should I add caching to services?**  
A: No. Cache at the script level if needed. Services stay stateless.

**Q: What if an endpoint needs custom headers?**  
A: Service accepts `request_dict` for flexibility. Caller can modify headers before passing to service.
