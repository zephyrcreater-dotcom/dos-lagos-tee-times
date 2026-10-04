import json

from src import state as state_module
from src.teeitup import TeeTime


def make_tee_time(unique_id, spots):
    return TeeTime(
        date="2026-10-10",
        time="07:30",
        available_spots=spots,
        price=47.0,
        booking_url="https://example.test/book",
        unique_id=unique_id,
        rate_name="18 Holes",
    )


class TestLoadState:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = state_module.load_state(tmp_path / "does_not_exist.json")
        assert result == {}

    def test_loads_existing_state(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"abc": 2}))
        result = state_module.load_state(path)
        assert result == {"abc": 2}

    def test_malformed_json_returns_empty_dict(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not valid json")
        result = state_module.load_state(path)
        assert result == {}

    def test_non_object_json_returns_empty_dict(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps([1, 2, 3]))
        result = state_module.load_state(path)
        assert result == {}


class TestSaveState:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "nested" / "state.json"
        state_module.save_state(path, {"abc": 3})
        assert state_module.load_state(path) == {"abc": 3}


class TestFindNewlyAvailable:
    def test_unseen_tee_time_is_new(self):
        tee_time = make_tee_time("slot-1", spots=4)
        result = state_module.find_newly_available([tee_time], state={})
        assert result == [tee_time]

    def test_unchanged_tee_time_is_not_new(self):
        tee_time = make_tee_time("slot-1", spots=4)
        result = state_module.find_newly_available([tee_time], state={"slot-1": 4})
        assert result == []

    def test_decreased_availability_is_not_new(self):
        tee_time = make_tee_time("slot-1", spots=2)
        result = state_module.find_newly_available([tee_time], state={"slot-1": 4})
        assert result == []

    def test_reopened_slot_counts_as_new(self):
        # Previously fully booked (0 tracked spots), now has spots again.
        tee_time = make_tee_time("slot-1", spots=2)
        result = state_module.find_newly_available([tee_time], state={"slot-1": 0})
        assert result == [tee_time]

    def test_increased_availability_counts_as_new(self):
        tee_time = make_tee_time("slot-1", spots=4)
        result = state_module.find_newly_available([tee_time], state={"slot-1": 2})
        assert result == [tee_time]


class TestUpdateState:
    def test_adds_new_entries(self):
        tee_time = make_tee_time("slot-1", spots=4)
        updated = state_module.update_state([tee_time], state={})
        assert updated == {"slot-1": 4}

    def test_does_not_mutate_unrelated_entries(self):
        tee_time = make_tee_time("slot-1", spots=4)
        updated = state_module.update_state([tee_time], state={"slot-2": 1})
        assert updated == {"slot-1": 4, "slot-2": 1}

    def test_original_state_dict_is_not_mutated(self):
        original = {"slot-2": 1}
        tee_time = make_tee_time("slot-1", spots=4)
        state_module.update_state([tee_time], state=original)
        assert original == {"slot-2": 1}
