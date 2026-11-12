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
		
		self.timer = op('timer1')
		self.timer.par.initialize.pulse()

		TDF.createProperty(self, 'A', value=self.DefaultScene, dependable=True, readOnly=False)
		TDF.createProperty(self, 'B', value=self.DefaultScene, dependable=True, readOnly=False)
		
	def SetScene(self, scene, track):
		attr = track.upper()
		getattr(self, attr).Deactivate(jump=True)
		getattr(self, attr).TurnOff()
		setattr(self, attr, scene)

	def GetSceneById(self,id):
		scene_ids = parent.Tracks.op('scene_ids')
		scene_row = scene_ids.row(str(id))
		scene_name = scene_row[2]
		scene = op.SCENES.op(scene_name)
		return scene

	def GetSceneOnTrack(self, track):
		return getattr(self, track.upper(), None)

	def FadeToNewScene(self, scene, force=False):
		if self._timer_active() and not force:
			return self._warn("fade blocked: timer is active (pass force=True to override)")
		self._toNewScene(scene, scene.par.Fade1.eval())

	def JumpToNewScene(self, scene, force=False):
		if self._timer_active() and not force:
			return self._warn("jump blocked: timer is active (pass force=True to override)")
		self._toNewScene(scene, 0)

	def _toNewScene(self, scene, length):
		self.B = self.A
		self.B.Deactivate(jump=False)
		self.A = scene
		scene.TurnOn()
		scene.Activate(jump=False)
		self._init_timer(length)

	def FadeToNewSceneId(self, scene_id, force=False):
		new_scene = self.GetSceneById(id=scene_id)
		self.FadeToNewScene(new_scene, force=force)

	def JumpToNewSceneId(self, scene_id, force=False):
		new_scene = self.GetSceneById(id=scene_id)
		self.JumpToNewScene(new_scene, force=force)

	def Fraction(self):
		"""0..1 progress of the current fade/jump."""
		return self.timer.fraction if self.timer else 0.0

	def TransitionDone(self):
		"""True when no fade/jump is currently in progress."""
		return not self._timer_active()

	def _timer_active(self):
		"""True while the Timer CHOP is mid-fade (0 < fraction < 1)."""
		return 0 < self.Fraction() < 1

	def _warn(self, text):
		lg = self.Logger
		(lg.Warning if lg else print)("Tracks: " + text)

	def _init_timer(self, length):
		if length == 0:
			length += 0.001
		self.timer.par.length = length
		self.timer.par.initialize.pulse()
		self.timer.par.start.pulse()

	def TimerDone(self):
		if parent.Tracks.A.name != parent.Tracks.B.name:
			self.B.TurnOff()
			self.SetScene(parent.Tracks.DefaultScene, 'b')
		
	@property
	def Logger(self):
		return op('logger')