"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""

from TDStoreTools import StorageManager
TDF = op.TDModules.mod.TDFunctions

class OscExt:
	"""
	OscExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		self.MaxIn = op('osc_in_max')
		self.MaxOut = op('osc_out_max')

		# {'address': ..., 'message': ...} for the last message out/in
		TDF.createProperty(self, 'LastSent', value={'address': '', 'message': ''}, dependable=True, readOnly=False)
		TDF.createProperty(self, 'LastReceived', value={'address': '', 'message': ''}, dependable=True, readOnly=False)

	def _send(self, address, message, store=True):
		"""The only place an outgoing OSC message reaches the wire."""
		self.MaxOut.sendOSC(address, message)
		if store:
			self.LastSent = {'address': address, 'message': message}

	def SendMode(self,mode,val):
		address = '/mode/' + mode
		message = val
		self._send(address, message)

	def SendStage(self,val):
		address = '/stage'
		message = val
		self._send(address, message)
		debug('Sent OSC: ', address, message)

	def SendCalibrationSteps(self,step,val):
		address = '/calibration/' + step
		message = val
		self._send(address, message)

	def SendOnlineClassification(self,relaxation,concentration):
		address = '/online_classification/vals'
		message = [relaxation,concentration]
		self._send(address, message)

	def Send(self,address,val,store=True):
		address = '/' + address
		message =[val]
		self._send(address, message, store)

	def OnReceive(self, address, message):
		"""
		Wire to the OSC In callback for MaxIn (Callbacks DAT, onReceiveOSC):
			def onReceiveOSC(dat, rowIndex, message, bytes, timeStamp, address, args, peer):
				parent().OnReceive(address, args)
		"""
		self.LastReceived = {'address': address, 'message': message}