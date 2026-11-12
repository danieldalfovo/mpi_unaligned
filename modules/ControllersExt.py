"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""

# ===========================================================================
# ControllersExt  -  fleet fan-out over the child Controller COMPs
#
# CONTROLLERS.tox holds one Controller clone per machina (see Controller.tox /
# ControllerExt.py). Every machina Pi runs its own MQTT broker + motors.py, so
# "talk to C-2" means "call the C2 Controller COMP", not "pass a bus address".
#
# This extension is a thin dispatcher: each verb below is the matching verb on
# ControllerExt, called on every child Controller - or just the one named in
# the last argument. Nothing here scales a value, builds a frame or knows the
# protocol; that all still lives in ControllerExt / motors.py.
#
#   op.CONTROLLERS.Realign()               -> {'A1':'all','A2':'all', ... }
#   op.CONTROLLERS.CalibrateHere()         -> {'A1':'all', ... }
#   op.CONTROLLERS.CalibrateHere("C2")     -> {'C2':'all'}
#   op.CONTROLLERS.CalibrateHere("A1", 1)  -> {'A1': 1}
#   op.CONTROLLERS.Command("WRITE","max_rpm_limit",50)          -> {'A1':'all', ... }
#   op.CONTROLLERS.Command("WRITE","max_rpm_limit",50,"C2")     -> {'C2':'all'}
#   op.CONTROLLERS.Command("WRITE","max_rpm_limit",50,1)        -> {'A1':'all'}
#   op.CONTROLLERS.Command("WRITE","max_rpm_limit",50,"A1",3)   -> {'A1': 3}
#
# `which` (see _select) picks the machina(s); the trailing `id` picks the motor
# on each, defaulting to broadcast (all motors). Every verb returns what it
# dispatched - {controller name: motor id, or 'all' for broadcast} - so the
# textport echo shows exactly what was hit. (Drive / Stop have no motor id and
# return a plain list of names.) To hit a single motor you can also just drop
# to its Controller COMP:
#   op.CONTROLLERS.op('C2').Command(3, "WRITE", "max_rpm_limit", 50)
# ===========================================================================

# motors.py broadcast address - mirrors ControllerExt.BROADCAST. Kept local so
# this file has no cross-extension import.
BROADCAST = 0

import TDFunctions as TDF


class ControllersExt:
	"""Fan a ControllerExt verb out to every child Controller COMP, or one."""

	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp
		self.Log = op("logger")
		# True only while every child Controller's Drive par is on (see SetDrive).
		TDF.createProperty(self, "Enable", value=False, dependable=True, readOnly=False)
		self._refresh_enable()
		# True only while every child Controller's MQTT client is connected (see CheckMqtt).
		TDF.createProperty(self, "Online", value=False, dependable=True, readOnly=False)
		self._refresh_online()
		
		# all motors off
		self.SetDrive(False)

	# -- target resolution ------------------------------------------------

	@staticmethod
	def _norm(s):
		"""Loose key for name matching: 'C-2' / 'c_2' / 'C 2' -> 'c2'."""
		return "".join(ch for ch in str(s).lower() if ch.isalnum())

	def _all(self):
		"""Every child Controller COMP, sorted by name for a stable index."""
		kids = [c for c in self.ownerComp.children
		        if c.isCOMP and hasattr(c, "Command") and hasattr(c, "Realign")]
		return sorted(kids, key=lambda c: c.name)

	def _select(self, which):
		"""
		Resolve `which` to a list of Controller COMPs.

			None / "all" / "*"   -> every controller
			"C2" / "C-2"         -> name match (case / -/_/space insensitive)
			2                    -> "C2" if that name exists, else the 2nd
			                        controller (1-based, sorted by name)
			["A1", "C2"]         -> the union of those
			a COMP               -> passed straight through
		"""
		everyone = self._all()

		if which in (None, "", "all", "*"):
			return everyone

		if isinstance(which, (list, tuple, set)):
			out = []
			for w in which:
				for c in self._select(w):
					if c not in out:
						out.append(c)
			return out

		if hasattr(which, "isCOMP") and which.isCOMP:
			return [which]

		hit = [c for c in everyone if self._norm(c.name) == self._norm(which)]
		if hit:
			return hit

		if str(which).isdigit():
			i = int(which)
			if 1 <= i <= len(everyone):
				return [everyone[i - 1]]

		self._warn("unknown controller {!r} (have: {})".format(
			which, ", ".join(c.name for c in everyone) or "none"))
		return []

	def _fan(self, verb, args=(), which=None, id=None):
		"""
		Call `verb(*args)` on each selected Controller.

		Returns what was actually dispatched: {controller name: target}, where
		target is the motor id, or "all" for broadcast. For verbs with no motor
		concept (Drive / Stop) pass id=None and a plain list of names comes back.
		"""
		hit = {}
		for c in self._select(which):
			fn = getattr(c, verb, None)
			if fn is None:
				self._warn("{} has no {}() - is ControllerExt promoted?".format(c.name, verb))
				continue
			fn(*args)
			hit[c.name] = ("all" if id == BROADCAST else id)
		return list(hit) if id is None else hit

	def _warn(self, text):
		(self.Log.Warning if self.Log else print)("Controllers: " + text)

	# -- raw passthrough ------------------------------------------------

	def Command(self, function_code, register=None, data=None, which=None, id=BROADCAST):
		"""
		Send a raw motors.py command to every machina (or just `which`),
		to every motor (or just `id`).

		Same as ControllerExt.Command() with the motor id moved to the end and
		defaulted to broadcast. `data` must already be the physical value the
		register expects. Run Lookup() for the register cheat-sheet.

			op.CONTROLLERS.Command("STOP")
			op.CONTROLLERS.Command("WRITE", "run_current_pct", 60)
			op.CONTROLLERS.Command("WRITE", "max_rpm_limit", 50, "C2")
			op.CONTROLLERS.Command("WRITE", "max_rpm_limit", 50, "C2", 3)
		"""
		return self._fan("Command", (id, function_code, register, data), which, id)

	def Subscribe(self, which=None):
		"""Enable the MQTT subscriptions (faultline/serial/logs) on the selected machina(s)."""
		return self._fan("Subscribe", (), which)

	def Unsubscribe(self, which=None):
		"""Disable the MQTT subscriptions (faultline/serial/logs) on the selected machina(s)."""
		return self._fan("Unsubscribe", (), which)

	def Each(self, verb, *args, **kw):
		"""
		Escape hatch: call any promoted ControllerExt method by name on each
		selected controller. `which=` picks the target(s); args pass straight
		through (so the motor id goes first, as in ControllerExt). The return
		is a plain list of the controller names hit.

			op.CONTROLLERS.Each("SetAccel", 0, 800, which="C2")
		"""
		return self._fan(verb, args, kw.pop("which", None))

	# -- actions ------------------------------------------------------

	def DoAction(self, action, which=None, id=BROADCAST):
		"""Run a named routine (see ControllerExt.ACTIONS) on the selected motors."""
		return self._fan("DoAction", (action, id), which, id)

	def Realign(self, which=None, id=BROADCAST):
		"""Re-sync the step counter to the encoder - fleet-wide, one machina, or one motor."""
		return self._fan("Realign", (id,), which, id)

	def CalibrateHere(self, which=None, id=BROADCAST):
		"""Capture the current angle as reference, persist, then realign."""
		return self._fan("CalibrateHere", (id,), which, id)

	# -- motion -----------------------------------------------------

	def Drive(self, radians, rpm, which=None):
		"""Broadcast a full DRIVE row (one record per motor) to each machina."""
		return self._fan("Drive", (radians, rpm), which)

	def DriveZero(self, which=None):
		"""Broadcast a DRIVE row of all zeros (0 rad / 0 rpm) to the selected machina(s)."""
		return self._fan("DriveZero", (), which)

	def Stop(self, which=None):
		"""Turn the Drive par off (SetDrive(False)), then hard park ramp and
		de-energize every motor on every machina. Release() undoes the Drive par."""
		self.SetDrive(False, which)
		#return self._fan("Stop", (), which)

	def Release(self, which=None):
		"""Turn the Drive par back on (SetDrive(True)) so driving resumes."""
		return self.SetDrive(True, which)

	def Hold(self, which=None, id=BROADCAST):
		"""Freeze the selected motors at their current position, no state change."""
		return self._fan("Hold", (id,), which, id)

	# -- parameters -------------------------------------------------

	def SetDrive(self, state, which=None):
		"""
		Set the `Drive` parameter on the selected Controller COMP(s) - not a
		motors.py command, just the local toggle on the COMP.

			op.CONTROLLERS.SetDrive(True)                 -> every controller
			op.CONTROLLERS.SetDrive(False, "C2")          -> just C2
			op.CONTROLLERS.SetDrive(1, ["A1", "C2"])      -> those two

		Returns {controller name: bool} for what was set. Also refreshes
		self.Enable: True only if every child Controller's Drive is now on.
		"""
		state = bool(state)
		hit = {}
		for c in self._select(which):
			par = getattr(c.par, "Drive", None)
			if par is None:
				self._warn("{} has no Drive parameter".format(c.name))
				continue
			par.val = state
			hit[c.name] = state
		self._refresh_enable()
		return hit

	def _refresh_enable(self):
		"""Enable = True only if every child Controller has its Drive par on."""
		everyone = self._all()
		self.Enable = bool(everyone) and all(
			getattr(c.par, "Drive", None) is not None and bool(c.par.Drive.eval())
			for c in everyone)

	# -- MQTT health ----------------------------------------------------

	def _mqtt(self, c):
		"""The MQTTExtension instance for one child Controller COMP."""
		return c.ext.ControllerExt.Mqtt.ext.MQTTExtension

	def CheckMqtt(self, which=None):
		"""Live MQTT connected status for each selected machina (refreshes Online).
		Returns {controller name: bool}."""
		hit = {c.name: bool(self._mqtt(c).CheckStatus(False)) for c in self._select(which)}
		self._refresh_online()
		return hit

	def _refresh_online(self):
		"""Online = True only if every child Controller's MQTT client is connected."""
		everyone = self._all()
		self.Online = bool(everyone) and all(
			bool(self._mqtt(c).CheckStatus(False)) for c in everyone)

	def EnsureMqtt(self, which=None):
		"""Reinit the MQTT extension on each selected machina whose client is
		not connected (refreshes Online). Returns {controller name: 'connected' | 'reinit'}."""
		hit = {}
		for c in self._select(which):
			mqtt = c.ext.ControllerExt.Mqtt
			if mqtt.ext.MQTTExtension.CheckStatus(False):
				hit[c.name] = "connected"
			else:
				mqtt.par.reinitextensions.pulse()
				hit[c.name] = "reinit"
		self._refresh_online()
		return hit

	# -- supervisor ---------------------------------------------------

	def ConnectSupervisor(self, which=None):
		"""Create/refresh the Supervisor XML-RPC client on the selected machina(s)."""
		return self._fan("ConnectSupervisor", (), which)

	def StartProcess(self, name, which=None):
		"""Start a supervised process (e.g. 'motors') on the selected machina(s)."""
		return self._fan("StartProcess", (name,), which)

	def StopProcess(self, name, which=None):
		"""Stop a supervised process (e.g. 'motors') on the selected machina(s)."""
		return self._fan("StopProcess", (name,), which)

	# -- register access (physical units, runtime only) -------------

	def Write(self, register, value, which=None, id=BROADCAST):
		"""Write one register on the selected machina(s) / motor(s)."""
		return self._fan("Write", (id, register, value), which, id)

	def Read(self, register, which, id):
		"""
		Ask one motor for a register value; the reply lands on that Controller's
		'serial' property. Needs a single machina and a single motor id - not
		broadcast.
		"""
		return self._fan("Read", (id, register), which, id)

	def SetVelocity(self, rpm, which=None, id=BROADCAST):
		"""Target velocity in rpm."""
		return self._fan("SetVelocity", (id, rpm), which, id)

	def SetAccel(self, accel_rpm_s, decel_rpm_s=None, which=None, id=BROADCAST):
		"""Ramp rates in rpm/s. decel defaults to accel."""
		return self._fan("SetAccel", (id, accel_rpm_s, decel_rpm_s), which, id)

	def SetCurrent(self, run_pct, hold_pct=None, which=None, id=BROADCAST):
		"""Driver current in percent (0..100)."""
		return self._fan("SetCurrent", (id, run_pct, hold_pct), which, id)

	# -- introspection ---------------------------------------------

	def Names(self):
		"""The child Controller COMP names, in the order an int `which` uses."""
		return [c.name for c in self._all()]

	def Controllers(self, which=None):
		"""The Controller COMP objects `which` resolves to (default: all)."""
		return self._select(which)

	def Lookup(self, token=None):
		"""Protocol cheat-sheet - delegates to the first controller."""
		first = self._all()
		if not first:
			return self._warn("no child Controller COMPs found")
		return first[0].Lookup(token)
