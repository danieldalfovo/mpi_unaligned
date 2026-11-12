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

from xmlrpc.client import ServerProxy

class SupervisorExt:
	"""
	SupervisorExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		self.Logger = op('logger')
		self.Server = None
		TDF.createProperty(self, 'State', value='', dependable=True, readOnly=False)

		TDF.createProperty(self, 'ProcessInfo', value=None, dependable=True, readOnly=False)
		self.Processes = ['main']
		for process in self.Processes:
			TDF.createProperty(self, op('namer')[process,1].val, value=None, dependable=True, readOnly=False)

	def getServer(self):
		return 'http://' + parent().par.Ip.eval() + ':' + str(parent().par.Port.eval())

	def Connect(self):
		"""
		Create the XML-RPC client and pull the current state/process info.

		Not done on init - the Pi's supervisord may not be reachable yet when
		this COMP is created (project load, a fresh clone, network not up
		yet), and ServerProxy() + getState() blocking in __init__ would hold
		up TD starting. Call this once the machina is expected to be up, or
		whenever you want to (re)connect.
		"""
		try:
			self.Server = ServerProxy(self.getServer())
			self.State = self.Server.supervisor.getState()['statename']
			self.Logger.Info('Created Supervisor client: ' + str(self.Server) + ', State: ' + self.GetState())
		except Exception as e:
			self.Server = None
			self.Logger.Info('Couldnt create Supervisor client on: ' + self.getServer() + ' - ' + str(e))
			return

		if self.GetState() == 'RUNNING':
			try:
				self.GetAllProcessInfo()
			except Exception as e:
				self.Logger.Warning('Couldnt get process info: ' + str(e))

	# general Supervisor commands

	def GetSupervisorState(self):
		return self.Server.supervisor.getState()

	def SetState(self, state):
		self.State = state

	def GetState(self):
		return self.State

	def Shutdown(self):
		if self.GetState() == 'RUNNING':
			self.Server.supervisor.shutdown()

	def Restart(self):
		if self.GetState() == 'RUNNING':
			self.Server.supervisor.restart()

	# process commands:
	# motormaster-can0 / motormaster-can1 / broker / websockets / hhtpserver

	def GetProcessInfo(self, name):
		if self.GetState() == 'RUNNING':
			return self.Server.supervisor.getProcessInfo(name)

	def GetAllProcessInfo(self):
		if self.GetState() == 'RUNNING':
			self.SetState('')
			self.ProcessInfo = self.Server.supervisor.getAllProcessInfo()
			for object in self.ProcessInfo:
				setattr(self, op('namer')[object['name'],1].val, object['statename'])
			self.SetState(self.Server.supervisor.getState()['statename'])

	def StartProcess(self, name):
		if self.GetState() == 'RUNNING': # was ==
			try:
				self.Server.supervisor.startProcess(name)
				self.Logger.Info('Started process: ' + name)
			except Exception as e:
				self.Logger.Warning('Unable to start process: ' + name + ' with error: ' + str(e))
			self.GetAllProcessInfo()

	def StopProcess(self, name):
		if self.GetState() == 'RUNNING':
			try:
				self.Server.supervisor.stopProcess(name)
				self.Logger.Info('Stopped process: ' + name)
			except Exception as e:
				self.Logger.Warning('Unable to start process: ' + name + ' with error: ' + str(e))
			self.GetAllProcessInfo()
