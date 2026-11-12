"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""

import TDFunctions as TDF

import json

# ===========================================================================
# Protocol mirror  (Slat-Control v0.3)
#
# The NAMES below are the whole contract with motors.py on the Linux box.
# Wire format, fixed-point scaling, range-checking, CRC16 and COBS all live
# there (Modules/motors.py + docs/protocol.md). Nothing in this file encodes
# bytes or scales a value - that duplication is exactly what used to drift
# out of sync. Send physical units (radians, rpm, %, ms, bool) and register
# names; the Pi does the rest.
# ===========================================================================

BROADCAST  = 0
MAX_MOTORS = 24

# function_code strings accepted by motors.py handle_command()
FUNCTION_CODES = ("HOLD", "WRITE", "READ", "DRIVE", "STOP", "ACTION")

# named routines for ACTION / DoAction()
ACTIONS = ("realign", "calibrate_here")

# Reference cheat-sheet for Lookup() and for hand-writing Command().
#   (address, writable, unit, range / notes)
# addr/unit/range are DOCUMENTATION only - they are never used to build a
# frame, so a stale row here is a doc bug, not a runtime bug.
PROTOCOL_REGISTERS = {
	# name                       addr   w      unit      range / notes
	"motor_position":           (0x01, True,  "rad",    "absolute target angle"),
	"target_velocity":          (0x02, True,  "rpm",    ">= 0"),
	"encoder_angle":            (0x03, False, "rad",    "measured"),
	"position_error":           (0x04, False, "rad",    "target - measured"),
	"target_position":          (0x05, False, "rad",    "active setpoint"),
	"actual_velocity":          (0x06, False, "rpm",    "signed, sign = direction"),
	"motor_state":              (0x00, False, "bits",   "enabled/fault/homed/rx_timeout/crc_error/stalled/fault_bus/driver_fault"),
	"enabled":                  (0x10, False, "bool",   ""),
	"fault":                    (0x11, False, "bool",   ""),
	"homed":                    (0x12, False, "bool",   ""),
	"rx_timeout":               (0x13, False, "bool",   ""),
	"crc_error":                (0x14, False, "bool",   ""),
	"stalled":                  (0x15, False, "bool",   ""),
	"fault_bus":                (0x16, False, "bool",   ""),
	"driver_fault":             (0x17, False, "bool",   ""),
	"encoder_fault":            (0x18, False, "bool",   ""),
	"max_rpm_limit":            (0x20, True,  "rpm",    ">= 0, runtime only"),
	"accel_rpm_s":              (0x21, True,  "rpm/s",  ">= 0, runtime only"),
	"decel_rpm_s":              (0x22, True,  "rpm/s",  ">= 0, runtime only"),
	"run_current_pct":          (0x30, True,  "%",      "0..100"),
	"hold_current_pct":         (0x31, True,  "%",      "0..100"),
	"microsteps":               (0x32, True,  "steps",  "1,2,4,8,16,32,64,128,256"),
	"reference_angle":          (0x40, True,  "rad",    "0 .. 2pi, persisted in EEPROM"),
	"fw_version":               (0x50, False, "dict",   "major/minor/patch/flags"),
	"fw_commit":                (0x51, False, "u32",    ""),
	"build_info":               (0x52, False, "dict",   "protocol_version/commits_since_tag"),
	"stall_follow_ratio":       (0x60, True,  "ratio",  "0.05 .. 0.80"),
	"stall_trip_travel":        (0x61, True,  "rad",    "0.0002 .. 0.524"),
	"stall_retry_cooldown_ms":  (0x62, True,  "ms",     "100 .. 60000"),
}

WRITABLE_REGISTERS = tuple(n for n, meta in PROTOCOL_REGISTERS.items() if meta[1])

# MQTT subscriptions:  topic -> (dependable property, extractor(payload) -> stored value)
# __init__ runs createProperty() for each; OnReceive() routes an incoming
# message to its property by topic.
SUBSCRIPTIONS = {
	"faultline": ("Faultline",      lambda msg: msg.get("state", msg)),
	"serial":    ("Serial", 		lambda msg: msg),
	# "heartbeat": ("Heartbeat",      lambda msg: msg.get("timestamp", msg)),
	"logs":      ("Logs",           lambda msg: msg),
}


class ControllerExt:
	"""
	Thin command layer over the MQTT bridge to motors.py on the Linux box.

	Every verb builds the dict that motors.py handle_command() expects
	({id, function_code, register, data}) and publishes it on 'command'.
	Responses (ACK / DATA / RESULT) arrive asynchronously on 'serial'
	- none of these methods return a device reply.
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		# client to publish vals + logger
		self.Mqtt = op("MQTT")
		self.Log  = op("logger")
		self.Supervisor = op("SUPERVISOR")

		# create subsciption containers
		for topic, (prop, _) in SUBSCRIPTIONS.items():
			TDF.createProperty(self, prop, value="UNSET", dependable=True, readOnly=False)

	# -- transport ----------------------------------------------------------

	def _publish(self, id, function_code, register=None, data=None):
		"""The only place a command dict reaches the wire."""
		self.Mqtt.Publish("command", {
			"id": int(id),
			"function_code": str(function_code).upper(),
			"register": register,
			"data": data,
		})

	def _warn(self, text):
		self.Log.Warning("Controller: " + text)
		
	def Subscribe(self):
		# machina subscriptions - one dependable property per topic (see SUBSCRIPTIONS)
		for topic, (prop, _) in SUBSCRIPTIONS.items():
			op("Sub_" + topic).par.Subscribe.pulse() # enable the subscription

	def Unsubscribe(self):
		"""Disable the MQTT subscriptions (faultline/serial/logs) for this machina.
		Leaves the dependable properties in place - they just stop updating."""
		for topic in SUBSCRIPTIONS:
			op("Sub_" + topic).par.Unsubscribe.pulse()

	# -- raw passthrough + lookup ----------------------------------------

	def Command(self, id, function_code, register=None, data=None):
		"""
		Raw passthrough to motors.py handle_command() on the Linux box.

		Nothing is scaled or re-encoded here. `data` must already be the
		physical value the register expects (radians, rpm, %, ms, bool) or,
		for DRIVE, {"goal_radians": [...], "goal_rpm": [...]}.
		`register` may be a name ("accel_rpm_s") or a number ("0x21" / 33) -
		motors.py resolves both. Run Lookup() for the cheat-sheet.

		Examples:
			op('Controller').Command(3, "WRITE", "accel_rpm_s", 800)
			op('Controller').Command(3, "READ",  "0x12")
			op('Controller').Command(0, "WRITE", "run_current_pct", 60)
			op('Controller').Command(0, "STOP")
		"""
		fc = str(function_code).upper()
		if fc not in FUNCTION_CODES and not fc.startswith("0X"):
			self._warn("Command: unusual function_code {!r} (sending anyway)".format(function_code))
		if not 0 <= int(id) <= 247:
			return self._warn("Command: motor id {} out of range 0..247".format(id))
		self._publish(id, fc, register, data)

	def Lookup(self, token=None):
		"""
		Print the protocol cheat-sheet to the textport (and return the rows).

			Lookup()          - everything
			Lookup("accel")   - registers whose name contains "accel"
			Lookup("stall")   - the stall-detector registers
			Lookup(0x21)      - the register at that address
		"""
		rows = []
		for name, (addr, w, unit, note) in PROTOCOL_REGISTERS.items():
			if isinstance(token, str) and token.lower() not in name.lower():
				continue
			if isinstance(token, int) and token != addr:
				continue
			rows.append((name, addr, w, unit, note))

		if token is None:
			print("--- function codes ---")
			print("  " + ", ".join(FUNCTION_CODES))
			print("--- actions (DoAction / ACTION) ---")
			print("  " + ", ".join(ACTIONS))

		print("--- registers (name  addr  rw  unit  notes) ---")
		for name, addr, w, unit, note in rows:
			print("  {:<26} 0x{:02X}  {:<2}  {:<6}  {}".format(
				name, addr, "rw" if w else "r", unit, note))
		if not rows:
			print("  (no register matches {!r})".format(token))
		return rows

	# -- motion -----------------------------------------------------------

	def Drive(self, radians, rpm):
		"""
		Broadcast a full DRIVE row. One record per motor, list index = motor
		id - 1 (record 0 -> id 1). Values are physical: radians and rpm.

		Fire-and-forget - safe to call every cook.
		"""
		radians, rpm = list(radians), list(rpm)
		if len(radians) != len(rpm):
			return self._warn("Drive: position/velocity lists differ in length "
			                  "({} vs {})".format(len(radians), len(rpm)))
		if len(radians) > MAX_MOTORS:
			return self._warn("Drive: {} records > {} motors".format(len(radians), MAX_MOTORS))

		self._publish(BROADCAST, "DRIVE", data={"goal_radians": radians, "goal_rpm": rpm})

	def DriveZero(self):
		"""
		Broadcast a DRIVE row of all zeros - 0 rad / 0 rpm for every motor.
		Motor count comes from len(op('goal_positions')), not a hardcoded
		number, so it always matches however many motors that table/CHOP
		currently carries.
		"""
		n = op('goal_positions').numSamples
		self.Drive([0] * n, [0] * n)

	def List(self, radians, rpm):
		"""
		Legacy: broadcast a DRIVE row on the old 'list' topic as
		{"data": {"goal_radians": [...], "goal_rpm": [...]}}.

		Superseded by Drive(), which goes through the unified 'command' path.
		Kept for motors.py builds that still route the 'list' topic through
		handle_list(). The Pi must subscribe to 'list' for this to be received.
		"""
		radians, rpm = list(radians), list(rpm)
		if len(radians) != len(rpm):
			return self._warn("List: position/velocity lists differ in length "
			                  "({} vs {})".format(len(radians), len(rpm)))
		if len(radians) > MAX_MOTORS:
			return self._warn("List: {} records > {} motors".format(len(radians), MAX_MOTORS))

		self.Mqtt.Publish("list", {"data": {"goal_radians": radians, "goal_rpm": rpm}})

	def Stop(self):
		"""Hard park ramp then de-energize, all motors. Not a latch - the next
		Drive() / position write moves again."""
		self._publish(BROADCAST, "STOP")

	def Hold(self, id=BROADCAST):
		"""Freeze at the current position, no state change."""
		self._publish(id, "HOLD")

	# -- register access ------------------------------------------------

	def Write(self, id, register, value):
		"""
		Write a physical value to a register. Broadcast (id=0) is
		fire-and-forget; a single id gets an ACK on 'serial_response'.
		"""
		if register not in WRITABLE_REGISTERS:
			return self._warn("Write: {!r} is not a writable register "
			                  "(run Lookup())".format(register))
		self._publish(id, "WRITE", register=register, data=value)

	def Read(self, id, register):
		"""Ask one motor for a register value; the reply lands on 'serial_response'."""
		if id == BROADCAST:
			return self._warn("Read: needs a single motor id, not broadcast")
		if register not in PROTOCOL_REGISTERS:
			return self._warn("Read: unknown register {!r} (run Lookup())".format(register))
		self._publish(id, "READ", register=register)

	def SetPosition(self, id, radians):
		"""Absolute target angle in radians. No scaling here - the Pi applies it."""
		self.Write(id, "motor_position", radians)

	def SetVelocity(self, id, rpm):
		"""Target velocity in rpm."""
		self.Write(id, "target_velocity", rpm)

	def SetAccel(self, id, accel_rpm_s, decel_rpm_s=None):
		"""
		Ramp rates in rpm/s. `decel_rpm_s` defaults to `accel_rpm_s` for a
		symmetric ramp. Two WRITEs. Runtime only - not persisted.
		"""
		if decel_rpm_s is None:
			decel_rpm_s = accel_rpm_s
		self.Write(id, "accel_rpm_s", accel_rpm_s)
		self.Write(id, "decel_rpm_s", decel_rpm_s)

	def SetCurrent(self, id, run_pct, hold_pct=None):
		"""
		Driver current as a percentage (0..100). `hold_pct` is left untouched
		when omitted. One or two WRITEs. Runtime only - not persisted.
		"""
		self.Write(id, "run_current_pct", run_pct)
		if hold_pct is not None:
			self.Write(id, "hold_current_pct", hold_pct)

	# -- actions --------------------------------------------------------

	def DoAction(self, action, id=BROADCAST):
		"""Run a named routine (see ACTIONS / Lookup()). The action id rides in
		the register byte of the frame - no payload."""
		if action not in ACTIONS:
			return self._warn("DoAction: unknown action {!r}; known: {}".format(
				action, ", ".join(ACTIONS)))
		self._publish(id, "ACTION", register=action)

	def Realign(self, id=BROADCAST):
		"""Re-sync the step counter to the encoder."""
		self.DoAction("realign", id)

	def CalibrateHere(self, id=BROADCAST):
		"""Capture the current angle as reference, persist, then realign."""
		self.DoAction("calibrate_here", id)

	# -- supervisor -------------------------------------------------

	def ConnectSupervisor(self):
		"""Create/refresh this machina's Supervisor XML-RPC client (see
		SupervisorExt.Connect - not done on init, since the Pi may not be up yet)."""
		self.Supervisor.Connect()

	def StartProcess(self, name):
		"""Start a supervised process on this machina's Pi (e.g. 'motors')."""
		self.Supervisor.StartProcess(name)

	def StopProcess(self, name):
		"""Stop a supervised process on this machina's Pi (e.g. 'motors')."""
		self.Supervisor.StopProcess(name)

	# -- subscription callbacks ----------------------------------------

	def OnReceive(self, topic, payload):
		"""Router for every subscription in SUBSCRIPTIONS. Wire each MQTT Sub
		COMP's callback to call op('Controller').OnReceive(topic, payload);
		the matching dependable property is updated with the extracted value."""
		entry = SUBSCRIPTIONS.get(topic)
		if entry is None:
			return self._warn("OnReceive: no subscription for topic {!r}".format(topic))
		prop, extract = entry
		setattr(self, prop, extract(payload))