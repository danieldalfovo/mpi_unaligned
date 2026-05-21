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

class TracksExt:
	"""
	TracksExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		self.Scenes = parent.Tracks.par.Scenes.eval()
		self.DefaultScene = parent.Tracks.par.Defaultscene.eval()

		TDF.createProperty(self,'Track_A', value=self.DefaultScene, dependable=True, readOnly=False)
		TDF.createProperty(self,'Track_B', value=self.DefaultScene, dependable=True, readOnly=False)

		TDF.createProperty(self,'Fade',value=0,dependable=True,readOnly=False)

	def CrossfadeToNewScene(self, scene):
		if op.TRACKS.op('fading')[0] == 1:
			self.Logger.Info("Still fading")
			return
		if self.Fade == 0:
			self.Track_B = scene
			scene.TurnOn()
			scene.Activate(jump=False)
			if self.Track_A.name != self.Track_B.name:
				self.Track_A.Deactivate(jump=False)
		else:
			self.Track_A = scene
			scene.TurnOn()
			scene.Activate(jump=False)
			if self.Track_A.name != self.Track_B.name:
				self.Track_B.Deactivate(jump=False)
		self.Fade = (self.Fade + 1) % 2
		self.SetFilterTime(scene.par.Fade1)
	
	def SetFilterTime(self,time):
		op('filter_fade').par.width = time

	def GetTrack(self):
		return [self.Track_A,self.Track_B][self.Fade]

	def GetOffTrack(self):
		return [self.Track_A,self.Track_B][(self.Fade+1)%2]
	
	def SetOffTrack(self,scene):
		if self.Fade == 0:
			self.Track_B = scene
		else:
			self.Track_A = scene

	def SetScene(self,scene,track):
		if track == 'a':
			self.Track_A.Deactivate(jump=True)
			self.Track_A.TurnOff()
			self.Track_A = scene
		elif track == 'b':
			self.Track_B.Deactivate(jump=True)
			self.Track_B.TurnOff()
			self.Track_B = scene

	def GetSceneById(self,id):
		scene_ids = parent.Tracks.op('scene_ids')
		scene_row = scene_ids.row(str(id))
		scene_name = scene_row[2]
		scene = self.Scenes.op(scene_name)
		return scene

	def GetSceneOnTrack(self,track):
		scene = None
		if track == 'a':
			scene = self.Track_A
		elif track == 'b':
			scene = self.Track_B
		return scene

	def CrossfadeToNewScene_old(self,scene):
		self.InitTimer()
		self.Track_B.TurnOff()
		self.Track_B = self.Track_A
		self.Track_B.Deactivate(jump=False)
		self.Track_A = scene
		scene.TurnOn()
		scene.Activate(jump=False)
		
	def FadeToNewScene(self,scene,track):
		self.SetScene(scene=scene,track=track)
		scene.TurnOn()
		scene.Activate(jump=False)

	def JumpToNewScene(self,scene,track):
		self.SetScene(scene=scene,track=track)
		scene.TurnOn()
		scene.Activate(jump=True)
	
	def CrossfadeToNewSceneId(self,scene_id):
		new_scene = self.GetSceneById(id=scene_id)
		self.CrossfadeToNewScene(scene=new_scene)
	
	def FadeToNewSceneId(self,scene_id,track):
		new_scene = self.GetSceneById(id=scene_id)
		self.FadeToNewScene(scene=new_scene,track=track)

	def JumpToNewSceneId(self,scene_id,track):
		new_scene = self.GetSceneById(id=scene_id)
		self.JumpToNewScene(scene=new_scene,track=track)

	def InitTimer(self):
		timer = op('timer1')
		timer.par.length = self.Track_A.par.Fade1
		timer.par.initialize.pulse()
		timer.par.start.pulse()
		
	@property
	def Logger(self):
		return op('logger')