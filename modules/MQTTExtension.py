"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""

from xmlrpc.client import Boolean

import TDFunctions as TDF

import msgpack

class MQTTExtension:
	"""
	MQTTExtension description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		self.client = op('mqttclient1')
		TDF.createProperty(self, 'Connected', value=None)
		self.CheckStatus(True)
		
		self.Logger = op('logger')

		self.Subscribers = dict()

		self.Logger.Info("Initialize MQTT Client: {}. On Address: {}. Connection: {} ".format(parent().path, parent().par.Networkaddress,self.Connected))

	def CheckStatus(self, reconnect: Boolean):
		self.Connected = self.client.isConnected
		if reconnect and not self.Connected:
			self.Reconnect()
		return self.Connected

	def Reconnect(self):
		self.client.par.reconnect.pulse()
		self.CheckStatus(False)
	
	def Publish(self, topic: str, payload: dict):
		self.client.publish(topic, self.pack(payload))

	def client_subscribe(self, topic: str):
		self.client.subscribe(topic)

	def client_unsubscribe(self, topic: str):
		self.client.unsubscribe(topic)
	
	def Subscribe(self, COMP):
		if COMP.Topic() not in self.Subscribers:
			self.Subscribers.update({COMP.Topic():[COMP.path]})
			self.client_subscribe(COMP.Topic())
		else:
			self.Subscribers[COMP.Topic()].append(COMP.path)
		self.Logger.Info("Added Subscriber: {} with topic: {}".format(COMP.path, COMP.Topic()))

	def Unsubscribe(self, COMP):
		if COMP.Topic() not in self.Subscribers:
			self.Logger.Info("Couldnt Unsubscribe: {} with topic: {}: Not subscribed before".format(COMP.path, COMP.Topic()))
		else:
			current_subscribers = self.Subscribers.get(COMP.Topic())
			if len(current_subscribers) == 1:
				self.Subscribers.pop(COMP.Topic())
				self.client_unsubscribe(COMP.Topic())
			else:
				current_subscribers.remove(COMP.path)
			self.Logger.Info("Unsubscribed: {} with topic: {}".format(COMP.path, COMP.Topic()))


	def OnReceive(self, topic: str, payload):
		if topic in self.Subscribers:
			_payload = self.unpack(payload)
			for Subscriber in self.Subscribers[topic]:
				op(Subscriber).OnReceive(_payload)

	def pack(self, msg):
		return msgpack.packb(msg, use_bin_type=True)
    
	def unpack(self, packed_msg):
		return msgpack.unpackb(packed_msg, raw=False)