"""Provider endpoint identity and redirect policy for source-bearing requests."""
from urllib.parse import urlsplit
import urllib.error
import urllib.request


def same_endpoint(left: str, right: str) -> bool:
    def identity(value):
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                parsed.query or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError("Invalid provider endpoint")
        return (parsed.scheme, parsed.hostname.lower(),
                parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80),
                parsed.path.rstrip("/"))
    try:
        return identity(left) == identity(right)
    except ValueError:
        return False


class NoProviderRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Neither credentials nor source payloads may acquire a new recipient.
        # Configure the provider's final API URL instead of following redirects.
        error = urllib.error.HTTPError(req.full_url, code, "Provider redirects are disabled", headers, fp)
        error.close()
        raise error


def urlopen(request, *, timeout, context):
    opener = urllib.request.build_opener(
        NoProviderRedirects(), urllib.request.HTTPSHandler(context=context)
    )
    return opener.open(request, timeout=timeout)
