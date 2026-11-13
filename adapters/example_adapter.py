"""Fill predict() using your own model client, then pass this file to `run`."""
import json
import sys


def predict(request):
    # The complete fixed prompt is request["messages"][0]["content"].
    # Use a new conversation for EVERY call. Disable tools/retrieval/history.
    # Generation settings are in request["generation"].
    # Call your chosen local model, CLI, or client here, then parse its JSON output.
    # Return exactly {"id": ..., "level": integer, "label": ..., "reason": ...}.
    # Keep credentials inside your own client/environment, never in submissions.
    raise NotImplementedError("Connect your model client in predict(request)")


if __name__ == "__main__":
    request = json.load(sys.stdin)
    prediction = predict(request)
    json.dump(prediction, sys.stdout, ensure_ascii=False)
