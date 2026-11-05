from src.appointment_deduplication import decide_match


def test_high_similarity_merges_the_existing_appointment():
    result = decide_match(0.92, "apt-existing-7")

    assert result == {
        "decision": "merge",
        "matched_appointment_id": "apt-existing-7",
        "score": 0.92,
    }
