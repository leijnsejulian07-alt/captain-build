import copy
import unittest

from parking.integration.builder_loop_state import (
    authorize_builder_loop,
    new_builder_loop,
    transition_builder_loop,
)


SESSION = {
    "binding_digest": "a" * 64,
    "state_epoch": 7,
}


class BuilderLoopStateTests(unittest.TestCase):
    def test_happy_path_with_debug_recovery_and_preview(self):
        state = new_builder_loop(session=SESSION)
        self.assertEqual(state["phase"], "plan")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="build", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="test", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="debug", result="fail")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="test", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="review", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="preview", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="complete", result="pass")
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(state["last_result"], "pass")
        with self.assertRaises(PermissionError):
            transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="review", result="pass")

    def test_stale_epoch_fails_closed(self):
        state = new_builder_loop(session=SESSION)
        with self.assertRaises(PermissionError):
            authorize_builder_loop(state, session={**SESSION, "state_epoch": 8}, state_epoch=8)

    def test_session_swap_fails_closed(self):
        state = new_builder_loop(session=SESSION)
        with self.assertRaises(PermissionError):
            authorize_builder_loop(state, session={"binding_digest": "b" * 64, "state_epoch": 7}, state_epoch=7)

    def test_illegal_phase_skip_is_denied(self):
        state = new_builder_loop(session=SESSION)
        with self.assertRaises(PermissionError):
            transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="preview", result="pass")

    def test_complete_requires_pass(self):
        state = new_builder_loop(session=SESSION)
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="build", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="test", result="pass")
        state = transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="review", result="pass")
        with self.assertRaises(PermissionError):
            transition_builder_loop(state, session=SESSION, state_epoch=7, next_phase="complete", result="fail")

    def test_tamper_and_unknown_fields_fail_closed(self):
        state = new_builder_loop(session=SESSION)
        tampered = copy.deepcopy(state)
        tampered["phase"] = "complete"
        with self.assertRaises(ValueError):
            authorize_builder_loop(tampered, session=SESSION, state_epoch=7)
        extended = {**state, "prompt": "secret"}
        with self.assertRaises(ValueError):
            authorize_builder_loop(extended, session=SESSION, state_epoch=7)

    def test_projection_contains_no_raw_scope_or_content(self):
        state = new_builder_loop(session=SESSION)
        self.assertEqual(
            set(state),
            {"schema_version", "session_binding_digest", "state_epoch", "phase", "attempt", "last_result", "loop_digest"},
        )
        rendered = repr(state)
        for forbidden in ("chat_id", "project_id", "repo_scope", "prompt", "source_code", "api_key"):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
