"""Invidious Authentication API wrapper for subscription sync, live feed, and account features."""
from __future__ import annotations
import httpx
import webbrowser
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Try to import keyring for secure token storage
try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False
    keyring = None

log = logging.getLogger(__name__)

class InvidiousAuth:
    def __init__(self, instance_url: str):
        self.base = instance_url.rstrip("/")
        self.token: str | None = None
        self._callback_port = 8899  # Local server port for auth callback
        self._service_name = "whirltube"
        self._username = "invidious_token"
    
    def _get_secure_token(self) -> str | None:
        """Get token from secure storage if available."""
        if HAS_KEYRING and keyring:
            try:
                return keyring.get_password(self._service_name, self._username)
            except Exception as e:
                log.warning(f"Failed to get token from keyring: {e}")
        return None
    
    def _set_secure_token(self, token: str) -> bool:
        """Store token in secure storage if available."""
        if HAS_KEYRING and keyring and token:
            try:
                keyring.set_password(self._service_name, self._username, token)
                return True
            except Exception as e:
                log.warning(f"Failed to store token in keyring: {e}")
        return False
    
    def _delete_secure_token(self) -> bool:
        """Delete token from secure storage if available."""
        if HAS_KEYRING and keyring:
            try:
                keyring.delete_password(self._service_name, self._username)
                return True
            except Exception as e:
                log.warning(f"Failed to delete token from keyring: {e}")
        return False
    
    def request_token(self, scopes: list[str], expire: int = 31536000) -> str:
        """
        Open browser for user to authorize token.
        Starts local server to receive callback.
        
        scopes examples:
            [":feed"]  # Access to feed
            ["GET:subscriptions", "POST:subscriptions*"]  # Manage subs
            [":*"]  # Full access (not recommended)
        """
        callback_url = f"http://localhost:{self._callback_port}/callback"
        
        # Build authorization URL
        params = {
            "scopes": ",".join(scopes),
            "callback_url": callback_url,
            "expire": expire
        }
        auth_url = f"{self.base}/authorize_token"
        
        # Build full URL
        import urllib.parse
        query_string = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        full_url = f"{auth_url}?{query_string}"
        
        log.info(f"Opening authorization URL: {full_url}")
        
        # Open browser
        webbrowser.open(full_url)
        
        # Start local server to receive callback
        token_received = []
        
        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    query = parse_qs(urlparse(self.path).query)
                    if "token" in query:
                        received_token = query["token"][0]
                        token_received.append(received_token)
                        
                        # Send success response to browser
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(b"""
                        <html>
                          <head><title>Authorization Success</title></head>
                          <body>
                            <h1>Success!</h1>
                            <p>You can now close this window.</p>
                          </body>
                        </html>
                        """)
                    else:
                        self.send_response(400)
                        self.send_header("Content-type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"Bad request: no token")
                except Exception as e:
                    log.error(f"Error in auth callback: {e}")
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"Internal error")
            
            def log_message(self, format, *args):
                # Suppress server logs
                pass
        
        server = HTTPServer(("localhost", self._callback_port), CallbackHandler)
        
        # Wait for callback (timeout after 5 minutes)
        import time
        timeout = time.time() + 300  # 5 minutes
        while not token_received and time.time() < timeout:
            # Handle requests with 1-second timeout to allow checking timeout
            server.handle_request()
        
        if token_received:
            self.token = token_received[0]
            log.info("Authorization successful, token received")
            return self.token
        else:
            raise TimeoutError("Authorization timeout - please try again")
    
    def _make_auth_request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Make an authenticated request to Invidious API."""
        if not self.token:
            raise RuntimeError("Not authenticated - no token available")
        
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"
        kwargs["headers"] = headers
        
        url = f"{self.base}{endpoint}"
        
        with httpx.Client(timeout=15.0) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
    
    def get_feed(self, max_results: int = 60) -> list[dict]:
        """Get authenticated subscription feed - much faster than polling channels!"""
        try:
            response = self._make_auth_request(
                "GET", 
                "/api/v1/auth/feed",
                params={"max_results": max_results}
            )
            data = response.json()
            
            # Combine notifications and videos 
            videos = data.get("videos", [])
            notifications = data.get("notifications", [])
            
            # Return combined list (notifications first)
            return notifications + videos
        except Exception as e:
            log.error(f"Failed to get authenticated feed: {e}")
            # Fallback to empty list rather than crashing
            return []
    
    def get_subscriptions(self) -> list[dict]:
        """Get user's subscriptions from Invidious account."""
        response = self._make_auth_request("GET", "/api/v1/auth/subscriptions")
        return response.json()
    
    def subscribe(self, ucid: str) -> bool:
        """Subscribe to a channel via Invidious account."""
        try:
            self._make_auth_request("POST", f"/api/v1/auth/subscriptions/{ucid}")
            return True
        except Exception as e:
            log.error(f"Failed to subscribe to {ucid}: {e}")
            return False
    
    def unsubscribe(self, ucid: str) -> bool:
        """Unsubscribe from a channel via Invidious account."""
        try:
            self._make_auth_request("DELETE", f"/api/v1/auth/subscriptions/{ucid}")
            return True
        except Exception as e:
            log.error(f"Failed to unsubscribe from {ucid}: {e}")
            return False
    
    def get_channel_videos(self, ucid: str, sort: str = "newest") -> list[dict]:
        """Get recent videos from a specific subscribed channel."""
        response = self._make_auth_request(
            "GET", 
            f"/api/v1/auth/channels/{ucid}/videos",
            params={"sort": sort}
        )
        return response.json()
    
    def mark_watched(self, video_id: str) -> bool:
        """Mark a video as watched on Invidious account."""
        try:
            self._make_auth_request("POST", f"/api/v1/auth/history/{video_id}")
            return True
        except Exception as e:
            log.error(f"Failed to mark video {video_id} as watched: {e}")
            return False
    
    def get_watch_history(self) -> list[dict]:
        """Get watch history from Invidious account."""
        response = self._make_auth_request("GET", "/api/v1/auth/history")
        return response.json()


def is_valid_invidious_instance(url: str) -> bool:
    """Check if the given URL is a valid Invidious instance."""
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        
        # Remove trailing slash
        clean_url = url.rstrip("/")
        
        # Test if instance is working
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{clean_url}/api/v1/stats", headers={"User-Agent": "WhirlTube/1.0"})
            response.raise_for_status()
            
            # Basic check: response should be JSON with required fields
            data = response.json()
            required_fields = {"version", "openRegistrations", "totalUsers", "totalSubscriptions"}
            return all(field in data for field in required_fields)
    except Exception:
        return False