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

class SceneExt:
	"""
	SceneExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		# properties
		#TDF.createProperty(self, 'MyProperty', value=0, dependable=True,
		#				   readOnly=False)

		# attributes:
		#self.a = 0 # attribute
		#self.B = 1 # promoted attribute

		# stored items (persistent across saves and re-initialization):
		#storedItems = [
			# Only 'name' is required...
		#	{'name': 'StoredProperty', 'default': None, 'readOnly': False,
		#	 						'property': True, 'dependable': True},
		#]
		# Uncomment the line below to store StoredProperty. To clear stored
		# 	items, use the Storage section of the Component Editor
		
		# self.stored = StorageManager(self, ownerComp, storedItems)

		TDF.createProperty(self,'On',value=0,dependable=True,readOnly=False)
		TDF.createProperty(self,'Active',value=0,dependable=True,readOnly=False)
		
		self.Tracks = parent.Scene.par.Tracks.eval()
	
	def Save(self):
		path = parent.Scene.par.externaltox
		parent.Scene.save(path)

	def Reload(self):
		parent.Scene.par.reinitpulse.pulse()

	def TurnOn(self):
		self.On = 1
	
	def TurnOff(self):
		self.On = 0

	def Activate(self,jump):
		op('fader/fade_time').par.value0 = parent.Scene.par.Fade1
		self.Active = 1
		if jump:
			op('fader/speed1').par.resetvalue = 1
			op('fader/speed1').par.resetpulse.pulse()
	
	def Deactivate(self,jump):
		op('fader/fade_time').par.value0 = parent.Scene.par.Fade2
		self.Active = 0
		if jump:
			op('fader/speed1').par.resetvalue = 0
			op('fader/speed1').par.resetpulse.pulse()

	def PlayMe(self,jump):
		if jump:
			self.Tracks.JumpToNewScene(scene=parent.Scene,track='a')
		else:
			self.Tracks.CrossfadeToNewScene(scene=parent.Scene)