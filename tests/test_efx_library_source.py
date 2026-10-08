"""Regression tests for efx_library.py's per-function C# source extraction
and push-back helpers.

Covers two bugs caught during a live round-trip test against Pilot (not
mocked here, since catching them required the real server's XAML
deserializer -- but the shapes that triggered them are reproduced as fixed
synthetic Body XML so a regression doesn't need live credentials to catch):

1. Reserializing the whole Body via ElementTree.tostring() breaks the
   server's XAML deserializer (it rewrites namespace prefixes/formatting).
   Push-back must only touch the one Code attribute via string surgery.
2. A naive `<DirectiveStep\\b` boundary regex also matches XAML
   property-element tags like `<DirectiveStep.Action>`, truncating the
   search scope to nothing and hiding the Code attribute.
"""

import unittest

from kinetic_devops.efx_library import (
    _dotnet_xml_attribute_escape,
    _iter_custom_code_actions,
    _replace_code_attribute_for_step,
)
import xml.etree.ElementTree as ET


# Trimmed but structurally real shape of a live EfxFunction.Body: single
# DirectiveStep containing one CustomCodeAction, followed by the
# DirectiveStep.VisualProperties property-element sibling that previously
# confused the step-boundary regex.
SAMPLE_BODY = (
    '<?xml version="1.0" encoding="utf-16"?>'
    '<DirectiveDefinition2 AdditionalUsings="" Version="3" '
    'xmlns="clr-namespace:Ice.Lib.Bpm.Model;assembly=Ice.Lib.Bpm.Shared" '
    'xmlns:ilbma="clr-namespace:Ice.Lib.Bpm.Model.Actions;assembly=Ice.Lib.Bpm.Shared" '
    'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
    '<DirectiveDefinition2.StartNode>'
    '<DirectiveStep Next="{x:Null}" x:Name="__ReferenceID0" '
    'DisplayName="Execute Custom Code 0" Id="b25d6018-8fdd-4039-907a-ace813c17078">'
    '<DirectiveStep.Action>'
    '<ilbma:CustomCodeAction Code="var x = 1;&#xA;var y = 2;" '
    'ExecutionRule="OnceForAllAffected" Id="0" IsAsync="False" '
    'PrimaryTable="" RecordMode="Nothing" TerminateOnError="False" '
    'ValidationState="Valid" />'
    '</DirectiveStep.Action>'
    '<DirectiveStep.VisualProperties>'
    '<VisualPropertiesStorage><x:Int64 x:Key="ElementX">209</x:Int64></VisualPropertiesStorage>'
    '</DirectiveStep.VisualProperties>'
    '</DirectiveStep>'
    '</DirectiveDefinition2.StartNode>'
    '</DirectiveDefinition2>'
)


class TestIterCustomCodeActions(unittest.TestCase):
    def test_finds_the_directive_step_and_action(self):
        root = ET.fromstring(SAMPLE_BODY)
        pairs = list(_iter_custom_code_actions(root))
        self.assertEqual(len(pairs), 1)
        step, action = pairs[0]
        self.assertIsNotNone(step)
        self.assertEqual(step.get("Id"), "b25d6018-8fdd-4039-907a-ace813c17078")
        self.assertEqual(step.get("DisplayName"), "Execute Custom Code 0")
        self.assertEqual(action.get("Code"), "var x = 1;\nvar y = 2;")


class TestDotnetXmlAttributeEscape(unittest.TestCase):
    def test_escapes_match_observed_server_encoding(self):
        raw = 'if (x > 1 && y < 2) { s = "hi"; }\nnext();\t// tab'
        escaped = _dotnet_xml_attribute_escape(raw)
        self.assertNotIn("\n", escaped)
        self.assertNotIn("\t", escaped)
        self.assertIn("&gt;", escaped)
        self.assertIn("&lt;", escaped)
        self.assertIn("&amp;&amp;", escaped)
        self.assertIn("&quot;", escaped)
        self.assertIn("&#xA;", escaped)
        self.assertIn("&#x9;", escaped)


class TestReplaceCodeAttributeForStep(unittest.TestCase):
    def test_replaces_only_the_target_code_attribute(self):
        new_body = _replace_code_attribute_for_step(
            SAMPLE_BODY, "b25d6018-8fdd-4039-907a-ace813c17078", "var z = 3;"
        )
        self.assertIn('Code="var z = 3;"', new_body)
        self.assertNotIn("var x = 1;", new_body)
        # Everything else must be untouched (regression guard for the
        # ElementTree.tostring() round-trip that broke the server's XAML
        # deserializer by rewriting namespace prefixes).
        self.assertIn('xmlns:ilbma="clr-namespace:Ice.Lib.Bpm.Model.Actions;assembly=Ice.Lib.Bpm.Shared"', new_body)
        self.assertIn("<DirectiveStep.VisualProperties>", new_body)
        self.assertIn('ValidationState="Valid"', new_body)

    def test_does_not_get_confused_by_directivestep_property_elements(self):
        # Regression guard: a naive `<DirectiveStep\b` boundary match also
        # matches `<DirectiveStep.Action>` / `<DirectiveStep.VisualProperties>`
        # (XAML property-element syntax), which previously truncated the
        # search scope before reaching the Code attribute at all.
        new_body = _replace_code_attribute_for_step(
            SAMPLE_BODY, "b25d6018-8fdd-4039-907a-ace813c17078", "ok();"
        )
        self.assertIn('Code="ok();"', new_body)

    def test_unknown_step_id_raises(self):
        with self.assertRaises(ValueError):
            _replace_code_attribute_for_step(SAMPLE_BODY, "does-not-exist", "x();")

    def test_preserves_multiline_code_as_character_references(self):
        new_body = _replace_code_attribute_for_step(
            SAMPLE_BODY, "b25d6018-8fdd-4039-907a-ace813c17078", "line1();\nline2();"
        )
        self.assertIn("line1();&#xA;line2();", new_body)
        # And round-tripping it back through parsing recovers the original text.
        root = ET.fromstring(new_body)
        _, action = next(_iter_custom_code_actions(root))
        self.assertEqual(action.get("Code"), "line1();\nline2();")


if __name__ == "__main__":
    unittest.main()
