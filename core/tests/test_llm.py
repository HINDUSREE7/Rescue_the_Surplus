import os
from unittest.mock import patch

from django.test import TestCase

from core import llm


class LLMTests(TestCase):
    def test_agreement_math(self):
        rules = {"category": "cooked_rice", "kg": 60.0, "allergens": ["none"]}
        self.assertEqual(llm.agreement(rules, {"kg": 60.0, "category": "cooked_rice"}), 1.0)
        self.assertEqual(llm.agreement(rules, {"kg": 30.0, "category": "cooked_rice"}), 0.5)
        self.assertEqual(llm.agreement(rules, {"kg": 30.0, "category": "curry_dal"}), 0.0)
        # No shared keys (and keys only on one side are ignored) gives 0.0.
        self.assertEqual(llm.agreement(rules, {"ready_by": "x"}), 0.0)
        self.assertEqual(llm.agreement({}, {"kg": 60.0}), 0.0)

    def test_stub_is_deterministic(self):
        stub = llm.StubLLM({"kg": 60.0})
        first, second = stub.extract("60 kilo biryani"), stub.extract("60 kilo biryani")
        self.assertEqual(first, second)
        self.assertEqual(first, {"kg": 60.0})
        first["kg"] = 1.0  # returned dict is a copy; the stub's reply is unchanged
        self.assertEqual(stub.extract("anything"), {"kg": 60.0})

    def test_get_extractor_none_when_url_unset(self):
        with patch.dict(os.environ, {}):
            os.environ.pop("RTS_LLM_URL", None)
            self.assertIsNone(llm.get_extractor())
