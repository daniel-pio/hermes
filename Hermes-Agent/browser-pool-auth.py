"""Read viewer credentials from a private file, never process arguments."""
import hmac
from pathlib import Path
from websockify.auth_plugins import BasicHTTPAuth


class FileAuth(BasicHTTPAuth):
    def validate_creds(self, username, password):
        expected = Path(self.src).read_text().rstrip('\n')
        return hmac.compare_digest(f'{username}:{password}'.encode(), expected.encode())
