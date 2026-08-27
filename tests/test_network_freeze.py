import socket

import pytest

from app.config import OutboundNetworkForbiddenError


def test_network_freeze_traps_outbound_connection():
    """Confirms that tests attempting outbound internet connections fail immediately."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(OutboundNetworkForbiddenError) as exc_info:
        s.connect(("8.8.8.8", 53))
    assert "Outbound network connection forbidden in test suite!" in str(exc_info.value)
    s.close()
