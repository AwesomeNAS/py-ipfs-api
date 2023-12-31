"""IPFS API Bindings for Python.

Classes:

 * Client – a TCP client for interacting with an IPFS daemon
"""

import os
import warnings

import multiaddr

DEFAULT_ADDR = multiaddr.Multiaddr(os.environ.get("PY_IPFS_HTTP_CLIENT_DEFAULT_ADDR", '/dns/localhost/tcp/5001/http'))
DEFAULT_BASE = str(os.environ.get("PY_IPFS_HTTP_CLIENT_DEFAULT_BASE", 'api/v0'))

VERSION_MINIMUM   = "0.4.21"
VERSION_BLACKLIST = []
VERSION_MAXIMUM   = "0.6.0"

from . import bitswap
from . import block
from . import bootstrap
from . import config
#TODO: `from . import dag`
from . import dht
from . import files
from . import key
from . import miscellaneous
from . import name
from . import object
from . import pin
from . import pubsub
from . import repo
#TODO: `from . import stats`
from . import swarm
from . import unstable

from .. import encoding, exceptions, multipart, utils


def assert_version(version, minimum=VERSION_MINIMUM, maximum=VERSION_MAXIMUM, blacklist=VERSION_BLACKLIST):
	"""Make sure that the given daemon version is supported by this client
	version.

	Raises
	------
	~ipfshttpclient.exceptions.VersionMismatch

	Parameters
	----------
	version : str
		The actual version of an IPFS daemon
	minimum : str
		The minimal IPFS daemon version to allowed
	maximum : str
		The maximum IPFS daemon version to allowed
	"""
	# Convert version strings to integer tuples
	version = list(map(int, version.split('-', 1)[0].split('.')))
	minimum = list(map(int, minimum.split('-', 1)[0].split('.')))
	maximum = list(map(int, maximum.split('-', 1)[0].split('.')))

	if minimum > version or version >= maximum:
		raise exceptions.VersionMismatch(version, minimum, maximum)
	
	for blacklisted in blacklist:
		blacklisted = list(map(int, blacklisted.split('-', 1)[0].split('.')))
		if version == blacklisted:
			raise exceptions.VersionMismatch(version, minimum, maximum)


def connect(addr=DEFAULT_ADDR, base=DEFAULT_BASE, *,
            chunk_size=multipart.default_chunk_size,
            session=False, **defaults):
	"""Create a new :class:`~ipfshttpclient.Client` instance and connect to the
	daemon to validate that its version is supported.

	Raises
	------
	~ipfshttpclient.exceptions.VersionMismatch
	~ipfshttpclient.exceptions.ErrorResponse
	~ipfshttpclient.exceptions.ConnectionError
	~ipfshttpclient.exceptions.ProtocolError
	~ipfshttpclient.exceptions.StatusError
	~ipfshttpclient.exceptions.TimeoutError


	All parameters are identical to those passed to the constructor of the
	:class:`~ipfshttpclient.Client` class.

	Returns
	-------
		:class:`~ipfshttpclient.Client`
	"""
	# Create client instance
	client = Client(addr, base, chunk_size=chunk_size, session=session, **defaults)

	# Query version number from daemon and validate it
	version_str = client.version()["Version"]
	assert_version(version_str)
	
	# Apply workarounds based on daemon version
	version = tuple(map(int, version_str.split('-', 1)[0].split('.')))
	if version < (0, 5):  # pragma: no cover (workaround)
		# Not really a workaround, but make use of HEAD requests on versions that
		# support them to speed things up if we are not interested in the response
		# anyways
		client._workarounds.add("use_http_head_for_no_result")

	return client


class Client(files.Base, miscellaneous.Base):
	"""The main IPFS HTTP client class
	
	Allows access to an IPFS daemon instance using its HTTP API by exposing an
	`IPFS Interface Core <https://github.com/ipfs/interface-ipfs-core/tree/master/SPEC>`__
	compatible set of methods.
	
	It is possible to instantiate this class directly, using the same parameters
	as :func:`connect`, to prevent the client from checking for an active and
	compatible version of the daemon. In general however, calling
	:func:`connect` should be preferred.
	
	In order to reduce latency between individual API calls, this class may keep
	a pool of TCP connections between this client and the API daemon open
	between requests. The only caveat of this is that the client object should
	be closed when it is not used anymore to prevent resource leaks.
	
	The easiest way of using this “session management” facility is using a
	context manager::
	
		with ipfshttpclient.connect() as client:
			print(client.version())  # These calls…
			print(client.version())  # …will reuse their TCP connection
	
	A client object may be re-opened several times::
	
		client = ipfshttpclient.connect()
		print(client.version())  # Perform API call on separate TCP connection
		with client:
			print(client.version())  # These calls…
			print(client.version())  # …will share a TCP connection
		with client:
			print(client.version())  # These calls…
			print(client.version())  # …will share a different TCP connection
	
	When storing a long-running :class:`Client` object use it like this::
	
		class Consumer:
			def __init__(self):
				self._client = ipfshttpclient.connect(session=True)
			
			# … other code …
			
			def close(self):  # Call this when you're done
				self._client.close()
	"""
	
	__doc__ += base.ClientBase.__doc__
	
	bitswap   = base.SectionProperty(bitswap.Section)
	block     = base.SectionProperty(block.Section)
	bootstrap = base.SectionProperty(bootstrap.Section)
	config    = base.SectionProperty(config.Section)
	dht       = base.SectionProperty(dht.Section)
	key       = base.SectionProperty(key.Section)
	name      = base.SectionProperty(name.Section)
	object    = base.SectionProperty(object.Section)
	pin       = base.SectionProperty(pin.Section)
	pubsub    = base.SectionProperty(pubsub.Section)
	repo      = base.SectionProperty(repo.Section)
	swarm     = base.SectionProperty(swarm.Section)
	unstable  = base.SectionProperty(unstable.Section)
	
	
	######################
	# SESSION MANAGEMENT #
	######################
	
	def __enter__(self):
		self._client.open_session()
		return self
	
	def __exit__(self, exc_type, exc_value, traceback):
		self.close()
	
	def close(self):
		"""Close any currently open client session and free any associated
		resources.
		
		If there was no session currently open this method does nothing. An open
		session is not a requirement for using a :class:`~ipfshttpclient.Client`
		object and as such all method defined on it will continue to work, but
		a new TCP connection will be established for each and every API call
		invoked. Such a usage should therefor be avoided and may cause a warning
		in the future. See the class's description for details.
		"""
		self._client.close_session()
	
	
	###########
	# HELPERS #
	###########

	@utils.return_field('Hash')
	@base.returns_single_item
	def add_bytes(self, data, **kwargs):
		"""Adds a set of bytes as a file to IPFS.

		.. code-block:: python

			>>> client.add_bytes(b"Mary had a little lamb")
			'QmZfF6C9j4VtoCsTp4KSrhYH47QMd3DNXVZBKaxJdhaPab'

		Also accepts and will stream generator objects.

		Parameters
		----------
		data : bytes
			Content to be added as a file

		Returns
		-------
			str
				Hash of the added IPFS object
		"""
		body, headers = multipart.stream_bytes(data, self.chunk_size)
		return self._client.request('/add', decoder='json',
		                            data=body, headers=headers, **kwargs)

	@utils.return_field('Hash')
	@base.returns_single_item
	def add_str(self, string, **kwargs):
		"""Adds a Python string as a file to IPFS.

		.. code-block:: python

			>>> client.add_str(u"Mary had a little lamb")
			'QmZfF6C9j4VtoCsTp4KSrhYH47QMd3DNXVZBKaxJdhaPab'

		Also accepts and will stream generator objects.

		Parameters
		----------
		string : str
			Content to be added as a file

		Returns
		-------
			str
				Hash of the added IPFS object
		"""
		body, headers = multipart.stream_text(string, self.chunk_size)
		return self._client.request('/add', decoder='json',
									data=body, headers=headers, **kwargs)

	def add_json(self, json_obj, **kwargs):
		"""Adds a json-serializable Python dict as a json file to IPFS.

		.. code-block:: python

			>>> client.add_json({'one': 1, 'two': 2, 'three': 3})
			'QmVz9g7m5u3oHiNKHj2CJX1dbG1gtismRS3g9NaPBBLbob'

		Parameters
		----------
		json_obj : dict
			A json-serializable Python dictionary

		Returns
		-------
			str
				Hash of the added IPFS object
		"""
		return self.add_bytes(encoding.Json().encode(json_obj), **kwargs)
	
	
	@base.returns_single_item
	def get_json(self, cid, **kwargs):
		"""Loads a json object from IPFS.

		.. code-block:: python

			>>> client.get_json('QmVz9g7m5u3oHiNKHj2CJX1dbG1gtismRS3g9NaPBBLbob')
			{'one': 1, 'two': 2, 'three': 3}

		Parameters
		----------
		cid : Union[str, cid.CIDv0, cid.CIDv1]
		   CID of the IPFS object to load

		Returns
		-------
			object
				Deserialized IPFS JSON object value
		"""
		return self.cat(cid, decoder='json', **kwargs)