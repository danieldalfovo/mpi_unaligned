"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""

from TDStoreTools import StorageManager
import TDFunctions as TDF

import types

class SubExtension:
	"""
	SubExtension description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp
		
		self.Client = op(parent().par.Client)

		self.Object = None

		type = self.Type()
		match type:
			case "Integer":
				self.Object = types.Integer(0)
			case "Float":
				self.Object = types.Float(0.0)
			case "String":
				self.Object = types.String("")
			case "Boolean":
				self.Object = types.Boolean(True)
			case "Custom":
				self.Object = types.Custom(parent().par.Key.eval(),0)
			case "Any":
				self.Object = types.Any(None)
			case _:
				self.Object = types.Val(None)
		
		if parent().par.Callbackdat != '':
			self.Callback = op(parent().par.Callbackdat).module
		else:
			self.Callback = None

	def Topic(self):
		return parent.Sub.par.Topic.eval()
	
	def Type(self):
		return parent.Sub.par.Type.eval()
	
	def Subscribe(self):
		self.Client.Subscribe(parent.Sub)
	
	def Unsubscribe(self):
		self.Client.Unsubscribe(parent.Sub)
	
	def GetVal(self):
		return self.Object.get_val()

	def OnReceive(self, payload):
		self.Object.set_val(payload)
		if self.Callback:
			self.Callback.on_receive(self.Topic(), self.Object)