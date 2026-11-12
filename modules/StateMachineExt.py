'''Info Header Start
Name : StateMachineExt
Author : ddalf@DD_01
Saveorigin : BuoyControl.31.toe
Saveversion : 2023.11880
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

class StateMachineExt:
	"""
	StateMachineExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		# properties
		TDF.createProperty(self, 'States', value=list(), dependable="deep", readOnly=False)
						   
		TDF.createProperty(self, 'State', value=None, dependable=True, readOnly=False)
		
		if op('opfind_states').valid:
			self.AddStateCOMPs()
			
		if parent.StateMachine.par.Initialize.eval():
			self.EnterState(parent.StateMachine.par.Initialize.eval())			

	def AppendState(self, state):
		self.States.append(state)

	def RemoveState(self, state):
		self.States.remove(state)

	def GetState(self, index):
		return self.States[index]

	def GetStates(self):
		return self.States
	
	def AddStateCOMPs(self):
		list = op('opfind_states')
		for state in list.rows():
			if state[0] != 'name':
				if op(state[0]) not in self.States:
					self.AppendState(op(state[0]))
	
	def EnterState(self, state):
		self.State = state
		state.OnEnter()
	
	def ExitState(self, state):
		state.OnExit()
		
	@property
	def Logger(self):
		return op('logger')