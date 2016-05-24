# Copyright 2014-2015 MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you
# may not use this file except in compliance with the License.  You
# may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.  See the License for the specific language governing
# permissions and limitations under the License.

"""Support for SSL in PyMongo."""

import atexit
import sys
import threading

HAVE_SSL = True
try:
    import ssl
except ImportError:
    HAVE_SSL = False

HAVE_CERTIFI = False
try:
    import certifi
    HAVE_CERTIFI = True
except ImportError:
    pass

HAVE_WINCERTSTORE = False
try:
    from wincertstore import CertFile
    HAVE_WINCERTSTORE = True
except ImportError:
    pass

from bson.py3compat import string_type
from pymongo.errors import ConfigurationError

_WINCERTSLOCK = threading.Lock()
_WINCERTS = None

if HAVE_SSL:
    try:
        # Python 3.2 and above.
        from ssl import SSLContext
    except ImportError:
        from pymongo.ssl_context import SSLContext

    def validate_cert_reqs(option, value):
        """Validate the cert reqs are valid. It must be None or one of the
        three values ``ssl.CERT_NONE``, ``ssl.CERT_OPTIONAL`` or
        ``ssl.CERT_REQUIRED``.
        """
        if value is None:
            return value
        elif isinstance(value, string_type) and hasattr(ssl, value):
            value = getattr(ssl, value)

        if value in (ssl.CERT_NONE, ssl.CERT_OPTIONAL, ssl.CERT_REQUIRED):
            return value
        raise ValueError("The value of %s must be one of: "
                         "`ssl.CERT_NONE`, `ssl.CERT_OPTIONAL` or "
                         "`ssl.CERT_REQUIRED" % (option,))

    def _load_wincerts():
        """Set _WINCERTS to an instance of wincertstore.Certfile."""
        global _WINCERTS

        certfile = CertFile()
        certfile.addstore("CA")
        certfile.addstore("ROOT")
        atexit.register(certfile.close)

        _WINCERTS = certfile

    # XXX: Possible future work.
    # - OCSP? Not supported by python at all.
    #   http://bugs.python.org/issue17123
    # - Setting OP_NO_COMPRESSION? The server doesn't yet.
    # - Adding an ssl_context keyword argument to MongoClient? This might
    #   be useful for sites that have unusual requirements rather than
    #   trying to expose every SSLContext option through a keyword/uri
    #   parameter.
    def get_ssl_context(*args):
        """Create and return an SSLContext object."""
        certfile, keyfile, ca_certs, cert_reqs, crlfile = args
        # Note PROTOCOL_SSLv23 is about the most misleading name imaginable.
        # This configures the server and client to negotiate the
        # highest protocol version they both support. A very good thing.
        ctx = SSLContext(ssl.PROTOCOL_SSLv23)
        if hasattr(ctx, "options"):
            # Explicitly disable SSLv2 and SSLv3. Note that up to
            # date versions of MongoDB 2.4 and above already do this,
            # python disables SSLv2 by default in >= 2.7.7 and >= 3.3.4
            # and SSLv3 in >= 3.4.3. There is no way for us to do this
            # explicitly for python 2.6 or 2.7 before 2.7.9.
            ctx.options |= getattr(ssl, "OP_NO_SSLv2", 0)
            ctx.options |= getattr(ssl, "OP_NO_SSLv3", 0)
        if certfile is not None:
            ctx.load_cert_chain(certfile, keyfile)
        if crlfile is not None:
            if not hasattr(ctx, "verify_flags"):
                raise ConfigurationError(
                    "Support for ssl_crlfile requires "
                    "python2 2.7.9+ (pypy 2.5.1+) or python3 3.4+")
            # Match the server's behavior.
            ctx.verify_flags = ssl.VERIFY_CRL_CHECK_LEAF
            ctx.load_verify_locations(crlfile)
        if ca_certs is not None:
            ctx.load_verify_locations(ca_certs)
        elif cert_reqs != ssl.CERT_NONE:
            # CPython >= 2.7.9 or >= 3.4.0, pypy >= 2.5.1
            if hasattr(ctx, "load_default_certs"):
                ctx.load_default_certs()
            # Python >= 3.2.0, useless on Windows.
            elif (sys.platform != "win32" and
                  hasattr(ctx, "set_default_verify_paths")):
                ctx.set_default_verify_paths()
            elif sys.platform == "win32" and HAVE_WINCERTSTORE:
                with _WINCERTSLOCK:
                    if _WINCERTS is None:
                        _load_wincerts()
                ctx.load_verify_locations(_WINCERTS.name)
            elif HAVE_CERTIFI:
                ctx.load_verify_locations(certifi.where())
            else:
                raise ConfigurationError(
                    "`ssl_cert_reqs` is not ssl.CERT_NONE and no system "
                    "CA certificates could be loaded. `ssl_ca_certs` is "
                    "required.")
        ctx.verify_mode = ssl.CERT_REQUIRED if cert_reqs is None else cert_reqs
        return ctx
else:
    def validate_cert_reqs(option, dummy):
        """No ssl module, raise ConfigurationError."""
        raise ConfigurationError("The value of %s is set but can't be "
                                 "validated. The ssl module is not available"
                                 % (option,))

    def get_ssl_context(*dummy):
        """No ssl module, raise ConfigurationError."""
        raise ConfigurationError("The ssl module is not available.")
