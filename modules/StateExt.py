'''Info Header Start
Name : StateExt
Author : ddalf@DD_25
Saveorigin : BuoyControl.59.toe
Saveversion : 2023.12000
Info Header End'''
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

import datetime

class StateExt:
	"""
	StateExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		self.Name = parent().par.Name.eval()
		self.Description = parent().par.Description.eval()
		self.Id = parent().par.Id.eval()

		self.timer = op('timer1')

		TDF.createProperty(self, 'Active', value=0, dependable=True, readOnly=False)

	def OnEnter(self):
		self.Active = 1
		if parent().par.Timeout.eval():
			self.timer.par.initialize.pulse()
			self.timer.par.start.pulse()
		run(op('trigger_on_enter').text, fromOP=parent.State, asParameter=True)
	
	def OnExit(self):
		run(op('trigger_on_exit').text, fromOP=parent.State, asParameter=True)
		if parent().par.Timeout.eval():
			self.timer.par.initialize.pulse()
		self.Active = 0