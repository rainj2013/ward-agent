from types import SimpleNamespace

from ward.api.routes import _resolve_conversation_id


class FakeConversations:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.created = 100

    def conversation_exists(self, conversation_id):
        return conversation_id in self.existing

    def create_conversation(self):
        return self.created


def test_valid_conversation_id_is_reused():
    history = SimpleNamespace(conversations=FakeConversations({7}))
    assert _resolve_conversation_id(7, history) == 7


def test_stale_conversation_id_is_replaced():
    history = SimpleNamespace(conversations=FakeConversations())
    assert _resolve_conversation_id(7, history) == 100
