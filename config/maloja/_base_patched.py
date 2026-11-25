from nimrodel import EAPI as API
from nimrodel import Multi

from ._exceptions import *

from copy import deepcopy
from types import FunctionType
import sys
import datetime

from doreah.logging import log

from bottle import response

from ..cleanup import CleanerAgent
from .. import database

__logmodulename__ = "apis"


cla = CleanerAgent()


class APIHandler:

	__apiname__: str
	errors: dict
	_instance = None

	def __new__(cls, *args, **kwargs):
		if not isinstance(cls._instance, cls):
			cls._instance = object.__new__(cls, *args, **kwargs)
		return cls._instance

	def __init_subclass__(cls):
		sf = cls.__base__.wrapper
		cls.wrapper = FunctionType(sf.__code__,sf.__globals__,sf.__name__,sf.__defaults__,sf.__closure__)
		cls.wrapper.__annotations__ = sf.__annotations__

		doc = "Accepts requests according to the <a href='{link}'>{name} Standard</a>"
		cls.wrapper.__doc__ = doc.format(name=cls.__apiname__,link=cls.__doclink__)

	def __init__(self):
		self.init()

		self.nimrodelapi = API(delay=True)
		self.nimrodelapi.get("{path}",pass_headers=True)(self.wrapper)
		self.nimrodelapi.post("{path}",pass_headers=True)(self.wrapper)
		self.nimrodelapi.get("",pass_headers=True)(self.wrapper)
		self.nimrodelapi.post("",pass_headers=True)(self.wrapper)

	def wrapper(self,path:Multi=[],**keys):
		log(f"{self.__apiname__} API request: {path}")

		# Inject HTTP headers into keys so Authorization header is accessible
		try:
			from bottle import request as bottle_request
			for header_name in ['Authorization', 'authorization']:
				header_val = bottle_request.headers.get(header_name)
				if header_val and header_name not in keys:
					keys[header_name] = header_val
					keys['Authorization'] = header_val
		except Exception:
			pass

		try:
			response.status,result = self.handle(path,keys)
		except Exception as e:
			for exc_type, exc_response in self.errors.items():
				if isinstance(e, exc_type):
					response.status, result = exc_response
					log(f"Error with {self.__apiname__} API: {e} (Request: {path})")
					break
			else:
				response.status, result = 500, {"status": "Unknown error", "code": 500}
				log(f"Unhandled Exception with {self.__apiname__} API: {e} (Request: {path})")

		return result

	def handle(self,path,keys):
		try:
			methodname = self.get_method(path, keys)
			method = self.methods[methodname]
		except KeyError:
			log(f"Could not find a handler for method {methodname} in API {self.__apiname__}", module="debug")
			log(f"Keys: {keys}", module="debug")
			raise InvalidMethodException()
		return method(path, keys)

	def scrobble(self,rawscrobble,client=None):
		return database.incoming_scrobble(rawscrobble,api=self.__apiname__,client=client)
