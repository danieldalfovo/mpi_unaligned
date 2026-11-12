"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""

# ===========================================================================
# CuelistExt  -  an ordered list of scene cues played as Timer CHOP segments
#
# The Timer CHOP owns the sequence: self.timer = op('timer1') is given a
# Segments DAT (one row per cue, built from the cue table) and it walks the
# timeline natively - cumulative time, per-segment progress, jump-to-time.
# This extension only:
#   - builds that segments table from the cue table,
#   - fires the cue's scene through the Tracks COMP on onSegmentEnter,
#   - pauses on a `hold` cue and loops on onDone.
#
# CUE TABLE  -  op('cues') by default, or a 'Cues' DAT par. First row = headers.
# Only `scene` is required:
#
#   scene      op path or name of the Scene COMP                    (required)
#   name       cue label                             (default: the scene name)
#   duration   seconds this cue runs                 (default: par Duration/10)
#   delay      seconds of pre-roll before it starts                 (default 0)
#   hold       1/0 - on reaching this cue, load it and wait for a GO (default 0)
#   jump       1/0 - hard cut instead of a crossfade                (default 0)
#   loopstart  1/0 - when Loop=1, OnDone() rewinds here instead of cue 1
#              (default: cue 1). Put this on the cue right after a hold=1
#              'reset' cue so each lap skips past reset instead of re-holding
#              there forever.
#
# GENERATED  -  op('segments') (created if missing): columns `length` `delay`,
# one row per cue, pointed at by the Timer CHOP's Segments DAT parameter.
#
# WIRING
#   - Timer CHOP  op('timer1'):  Length Units = Seconds, Cycle = off.
#   - Its Callbacks DAT (inside this COMP):
#         def onSegmentEnter(timerOp, segment, interrupt):
#             parent().OnSegmentEnter(segment, interrupt)
#         def onDone(timerOp, segment, interrupt):
#             parent().OnDone(segment, interrupt)
#   - parameter Extension 1 = op('./CuelistExt'), Promote on.
#   - optional global OP shortcut 'CUELIST'  ->  op.CUELIST.Start()
#   - required custom par:   Tracks (COMP)  -> the Tracks COMP that owns the
#                            crossfader; cues are fired through its
#                            FadeToNewScene() / JumpToNewScene().
#   - optional custom pars:  Cues (DAT)  Scenes (COMP)  Duration (float)
#                            Loop (toggle)  Segments (DAT)
#   - optional: a DAT Execute on the cue table calling  parent().Reload()
#
# STATE
#   op.CUELIST.State  ->  'stopped' | 'playing' | 'paused' | 'holding'
#   (dependable - bind UI buttons to it; .Playing stays 1 only while 'playing')
#   Callback (needs CallbacksExt + a Callbacks DAT, see the palette 'callbacksHelper'):
#       def onStateChange(info):     # info: state, previous, ownerComp, callbackName
#           ...
#
# USAGE
#   op.CUELIST.Start()                # from the top (or a given cue)
#   op.CUELIST.StartLoop()             # turn Loop on and Start()
#   op.CUELIST.StopLoop()              # turn Loop off (playback keeps going)
#   op.CUELIST.Pause() / .Resume() / .TogglePause()
#   op.CUELIST.Stop()                  # halt + reset to cue 1
#   op.CUELIST.Next() / .Previous()
#   op.CUELIST.Go(3) / .Go("sunrise") / .Go(op('SCENES/sunrise'))
#   op.CUELIST.GoToTime(90)  / .GoToFraction(0.5)     # scrub the whole show
#   op.CUELIST.Restart()              # re-fire the current cue from 0
#   op.CUELIST.SetLoopStart("after_reset")   # where OnDone() rewinds to when looping
# ===========================================================================

from TDStoreTools import StorageManager
import TDFunctions as TDF


class CuelistExt:
	"""Ordered scene cues from a Table DAT, played as native Timer CHOP segments."""

	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp
		self.timer = op('timer1')

		# transient state used across the Timer CHOP callbacks
		self._seek_target = None      # segment idx we're seeking to (suppresses transient enters)
		self._pending_jump = None     # hard-cut override for the next fired scene

		# Cues: [{name, scene, ref, duration, delay, hold, jump, row}, ...]
		TDF.createProperty(self, 'Cues',    value=list(), dependable="deep", readOnly=False)
		# Index is 1-based; 0 means nothing is loaded.
		TDF.createProperty(self, 'Index',   value=0,  dependable=True, readOnly=False)
		# Transport state: 'stopped' | 'playing' | 'paused' | 'holding' (waiting on a hold cue).
		# Playing is kept in sync (1 only while 'playing').
		TDF.createProperty(self, 'State',   value='stopped', dependable=True, readOnly=False)
		TDF.createProperty(self, 'Playing', value=0,  dependable=True, readOnly=False)
		TDF.createProperty(self, 'CueName', value='', dependable=True, readOnly=False)

		self.Reload()

	# -- small helpers --------------------------------------------------

	def _set_state(self, state):
		previous = self.State
		self.State = state
		self.Playing = int(state == 'playing')
		if state != previous and hasattr(self.ownerComp, 'DoCallback'):
			self.ownerComp.DoCallback('onStateChange', {'state': state, 'previous': previous})

	def _warn(self, text):
		lg = op('logger')
		(lg.Warning if lg else print)("Cuelist: " + text)

	def _par(self, name, default=None):
		"""Value of an optional custom parameter, or `default` if it isn't there."""
		p = getattr(self.ownerComp.par, name, None)
		return default if p is None else p.eval()

	def _set_par(self, name, value):
		"""Set an optional custom parameter, if this COMP has it."""
		p = getattr(self.ownerComp.par, name, None)
		if p is None:
			return self._warn("no {!r} custom par on this COMP".format(name))
		p.val = value

	def _loop(self):
		return self._truthy(self._par('Loop', 0))

	@staticmethod
	def _truthy(v, default=False):
		if v is None or v == '':
			return default
		return str(v).strip().lower() in ('1', 'true', 'yes', 'on', 'y', 't')

	@staticmethod
	def _num(v, default):
		try:
			return float(v)
		except (TypeError, ValueError):
			return default

	def _ch(self, *names):
		"""First existing Timer CHOP output channel as a float (0.0 if none)."""
		if not self.timer:
			return 0.0
		for n in names:
			c = self.timer[n]
			if c is not None:
				return float(c)
		return 0.0

	def _active(self):
		return bool(self._ch('timer_active', 'timerRunning', 'running'))

	# -- building the list + the segments table ----------------------

	def _dat(self):
		return self._par('Cues') or op('cues')

	def _segdat(self):
		"""The generated segments Table DAT (par 'Segments', op('segments'), or created)."""
		d = self._par('Segments') or op('segments')
		if d is None:
			try:
				d = self.ownerComp.create(tableDAT, 'segments')
				d.nodeX, d.nodeY = -400, -300
			except Exception as e:
				self._warn("couldn't create a 'segments' DAT: {}".format(e))
		return d

	def _resolve(self, ref):
		"""Cell -> Scene COMP. Tries the 'Scenes' container first, then op()."""
		ref = str(ref)
		box = self._par('Scenes')
		if box is not None:
			hit = box.op(ref)
			if hit is not None:
				return hit
		return op(ref)

	def Reload(self):
		"""(Re)read the cue table, rebuild self.Cues and the segments DAT."""
		dat = self._dat()
		cues = []
		if dat is None or dat.numRows < 2:
			self._warn("no cue table (par 'Cues' or op('cues')) or it's empty")
			self.Cues = cues
			return cues

		head = [c.val for c in dat.row(0)]

		def cell(row, *names):
			for n in names:
				if n in head:
					v = row[head.index(n)].val
					if v != '':
						return v
			return None

		def_dur = self._num(self._par('Duration', 10), 10)

		for r in range(1, dat.numRows):
			row = dat.row(r)
			ref = cell(row, 'scene', 'comp', 'op', 'path')
			if not ref:
				continue
			scene = self._resolve(ref)
			if scene is None:
				self._warn("row {}: scene {!r} not found".format(r, ref))
			cues.append({
				'name':     cell(row, 'name', 'cue', 'label') or (scene.name if scene else str(ref)),
				'scene':    scene,
				'ref':      str(ref),
				'duration': self._num(cell(row, 'duration', 'dur', 'time', 'length', 'seconds'), def_dur),
				'delay':    self._num(cell(row, 'delay', 'predelay', 'pre', 'prewait'), 0.0),
				'hold':     self._truthy(cell(row, 'hold', 'stop', 'wait', 'manual'), False),
				'jump':     self._truthy(cell(row, 'jump', 'cut', 'hard'), False),
				'loopstart': self._truthy(cell(row, 'loopstart', 'loopto', 'restart'), False),
				'row':      r,
			})

		self.Cues = cues
		self._build_segments()
		if not (1 <= self.Index <= len(cues)):
			self.Index = 1 if cues else 0
			self.CueName = cues[0]['name'] if cues else ''
		return cues

	def _build_segments(self):
		"""Write self.Cues out as `length`/`delay` rows and point the Timer at them."""
		segs = self._segdat()
		if segs is None:
			return
		segs.clear()
		segs.appendRow(['length', 'delay'])
		for cue in self.Cues:
			segs.appendRow([cue['duration'], cue['delay']])
		if self.timer:
			for pname in ('segdat', 'segmentdat', 'segments', 'segmentsdat'):
				p = getattr(self.timer.par, pname, None)
				if p is not None:
					p.val = segs
					break

	# -- cue pointer + firing --------------------------------------

	def _index_of(self, cue):
		"""Resolve int (1-based), cue name, ref, or Scene COMP -> int, or None."""
		if isinstance(cue, bool):
			return None
		if isinstance(cue, int):
			return cue if 1 <= cue <= len(self.Cues) else None
		if hasattr(cue, 'name') and not isinstance(cue, str):     # a COMP
			for k, c in enumerate(self.Cues, 1):
				if c['scene'] is cue:
					return k
			cue = cue.name
		key = str(cue).strip().lower()
		for k, c in enumerate(self.Cues, 1):
			if c['name'].lower() == key or c['ref'].lower().split('/')[-1] == key:
				return k
		return None

	def _loop_start(self):
		"""1-based index OnDone() rewinds to when looping. The first cue
		flagged `loopstart`, or cue 1 if none is marked."""
		for k, c in enumerate(self.Cues, 1):
			if c.get('loopstart'):
				return k
		return 1

	def _clamp(self, i):
		"""Keep i in range. While looping, wrap within [loopstart, last cue]
		instead of [1, last cue] - Next()/Previous() should cycle the same
		range OnDone() does, not fall back through the reset/hold cue."""
		n = len(self.Cues)
		if n == 0:
			return 0
		if self._loop():
			start = self._loop_start()
			span = n - start + 1
			return start + (i - start) % span
		return max(1, min(i, n))

	def _fire(self, cue, jump=None):
		scene = cue['scene']
		if scene is None:
			return self._warn("cue {!r} has no scene".format(cue['name']))
		tracks = self._par('Tracks')
		if tracks is None:
			return self._warn("no Tracks COMP (par 'Tracks')")
		hard = cue['jump'] if jump is None else bool(jump)
		if hard:
			tracks.JumpToNewScene(scene=scene)
		else:
			tracks.FadeToNewScene(scene=scene)

	def _go(self, i, jump=None):
		"""Seek the Timer CHOP to cue i (1-based) and keep playing."""
		if not self.Cues or not self.timer:
			return self._warn("no cues / no timer")
		i = self._clamp(i)
		idx0 = i - 1
		self._pending_jump = jump
		self._set_state('playing')
		self.timer.par.play = 1
		if not self._active():
			self._seek_target = idx0                 # skip the transient seg-0 enter
			self.timer.par.start.pulse()
		self.timer.goTo(segment=idx0)
		return self.Cues[idx0]

	# -- transport ------------------------------------------------

	def Start(self, cue=None):
		"""Begin playback - from `cue` if given, else the first cue."""
		if not self.Cues:
			return self._warn("nothing to play")
		if cue is not None:
			return self.Go(cue)
		self._set_state('playing')
		self._seek_target = 0
		self._pending_jump = None
		self.timer.par.play = 1
		self.timer.par.initialize.pulse()
		self.timer.par.start.pulse()
		return self.Cues[0]['name']

	def Play(self, cue=None):
		"""Alias for Start()."""
		return self.Start(cue)

	def StartLoop(self, cue=None):
		"""Turn the Loop par on and begin playback - from `cue` if given, else
		the loopstart cue (see SetLoopStart / cue 1 if none is marked). Unlike
		Start(), this skips the reset/hold cue at the top of the list, since
		the point of StartLoop() is to (re)enter the loop, not run reset again."""
		self._set_par('Loop', 1)
		if cue is not None:
			return self.Go(cue)
		return self._go(self._loop_start())

	def StopLoop(self):
		"""Turn the Loop par off, without touching playback."""
		self._set_par('Loop', 0)

	def Stop(self):
		"""Halt playback, reset to the top of the list, and force a fade to its
		first scene - even if Tracks is mid-transition. The fade itself owns
		re-initializing the Tracks Timer CHOP; this doesn't touch it directly."""
		self._set_state('stopped')
		self._seek_target = None
		self._pending_jump = None
		if self.timer:
			self.timer.par.initialize.pulse()
			self.timer.par.play = 1
		self.Index = 1 if self.Cues else 0
		self.CueName = self.Cues[0]['name'] if self.Cues else ''
		cue = self.Cues[0] if self.Cues else None
		scene = cue['scene'] if cue else None
		tracks = self._par('Tracks')
		if scene is not None and tracks is not None:
			tracks.FadeToNewScene(scene=scene, force=True)

	def Pause(self):
		"""Freeze the timer where it is (scene stays up). Only from 'playing'."""
		if self.State != 'playing':
			return
		self._set_state('paused')
		if self.timer:
			self.timer.par.play = 0

	def Resume(self):
		"""Continue a paused or held cue from where it stopped. Only from 'paused'/'holding'."""
		if self.State not in ('paused', 'holding'):
			return
		self._set_state('playing')
		if self.timer:
			self.timer.par.play = 1

	def TogglePause(self):
		"""Pause <-> Resume."""
		self.Pause() if self.State == 'playing' else self.Resume()

	def Next(self):
		"""Advance one cue. Obeys the Loop par; holds at the last cue otherwise."""
		if not self.Cues:
			return
		if self.Index >= len(self.Cues) and not self._loop():
			return self._warn("at the last cue")
		return self._go(self.Index + 1)

	def Previous(self):
		"""Step back one cue."""
		if not self.Cues:
			return
		return self._go(self.Index - 1)

	def Go(self, cue, jump=None):
		"""
		Jump straight to a cue and play it. `cue` is a 1-based index, a cue
		name, a scene name, or the Scene COMP itself. Starts playback if stopped.
		`jump=True` forces a hard cut for this cue.
		"""
		i = self._index_of(cue)
		if i is None:
			return self._warn("no such cue: {!r}".format(cue))
		return self._go(i, jump)

	def GoToCue(self, cue, jump=None):
		"""Alias for Go()."""
		return self.Go(cue, jump)

	def Restart(self):
		"""Re-fire the current cue from time 0."""
		return self._go(self.Index or 1)

	# -- scrubbing the whole timeline ---------------------------

	def GoToTime(self, seconds):
		"""Seek to an absolute time across the whole cue list (hard cut)."""
		if not self.Cues or not self.timer:
			return
		t = max(0.0, float(seconds))
		acc = 0.0
		for i, c in enumerate(self.Cues):
			last = i == len(self.Cues) - 1
			if t < acc + c['duration'] or last:
				self._pending_jump = True
				self.timer.goTo(segment=i, seconds=t - acc)
				self._set_state('playing' if self._active() else 'stopped')
				return c
			acc += c['duration']

	def GoToFraction(self, f):
		"""Seek to 0..1 of the whole cue list."""
		total = sum(c['duration'] for c in self.Cues)
		return self.GoToTime(max(0.0, min(float(f), 1.0)) * total)

	# -- Timer CHOP callbacks ----------------------------------

	def OnSegmentEnter(self, segment, interrupt=False):
		"""Wire to the Timer CHOP: parent().OnSegmentEnter(segment, interrupt)."""
		seg = int(segment)
		if self._seek_target is not None and seg != self._seek_target:
			return                                   # transient while seeking
		self._seek_target = None
		if not (0 <= seg < len(self.Cues)):
			return
		self.Index = seg + 1
		cue = self.Cues[seg]
		self.CueName = cue['name']
		self._fire(cue, self._pending_jump)
		self._pending_jump = None
		if cue['hold']:                               # wait here for a GO
			self._set_state('holding')
			if self.timer:
				self.timer.par.play = 0

	def OnDone(self, segment=None, interrupt=False):
		"""Wire to the Timer CHOP: parent().OnDone(segment, interrupt)."""
		if interrupt:
			return
		if self._loop() and self.Cues:
			self._go(self._loop_start())
		else:
			self._set_state('stopped')

	# -- introspection / helpers -------------------------------

	def GetCues(self):
		"""The full cue list (list of dicts)."""
		return list(self.Cues)

	def GetCue(self, cue):
		"""One cue dict by index / name / scene, or None."""
		i = self._index_of(cue)
		return self.Cues[i - 1] if i else None

	def CurrentCue(self):
		"""The loaded cue dict, or None."""
		return self.Cues[self.Index - 1] if 1 <= self.Index <= len(self.Cues) else None

	def CurrentScene(self):
		"""The loaded cue's Scene COMP, or None."""
		c = self.CurrentCue()
		return c['scene'] if c else None

	def Count(self):
		"""Number of cues."""
		return len(self.Cues)

	def Names(self):
		"""Cue labels in order."""
		return [c['name'] for c in self.Cues]

	def Segments(self):
		"""The generated (length, delay) rows, for inspection."""
		return [(c['duration'], c['delay']) for c in self.Cues]

	def Elapsed(self):
		"""Seconds into the current cue."""
		return self._ch('segment_seconds', 'timer_seconds')

	def Remaining(self):
		"""Seconds left in the current cue."""
		left = self._ch('segment_seconds_left')
		if left:
			return left
		c = self.CurrentCue()
		return max(0.0, c['duration'] - self.Elapsed()) if c else 0.0

	def Fraction(self):
		"""0..1 progress through the current cue."""
		return self._ch('segment_fraction', 'timer_fraction')

	def TransitionFraction(self):
		"""0..1 progress of the current Tracks fade/jump (0 if no Tracks COMP wired)."""
		tracks = self._par('Tracks')
		return tracks.Fraction() if tracks else 0.0

	def TransitionDone(self):
		"""True once the Tracks COMP's fade/jump has finished (or none is wired)."""
		tracks = self._par('Tracks')
		return tracks.TransitionDone() if tracks else True

	def TotalFraction(self):
		"""0..1 progress across the whole cue list."""
		total = sum(c['duration'] for c in self.Cues) or 1.0
		done = sum(c['duration'] for c in self.Cues[:max(0, self.Index - 1)])
		cur = 0.0
		c = self.CurrentCue()
		if c:
			cur = c['duration'] * self.Fraction()
		return (done + cur) / total

	# -- edit cues in memory (not written back to the DAT) -----

	def SetDuration(self, seconds, cue=None):
		"""Override a cue's run time. Defaults to the current cue."""
		c = self.GetCue(cue) if cue is not None else self.CurrentCue()
		if not c:
			return self._warn("SetDuration: no such cue {!r}".format(cue))
		c['duration'] = float(seconds)
		self._build_segments()

	def SetDelay(self, seconds, cue=None):
		"""Override a cue's pre-roll delay. Defaults to the current cue."""
		c = self.GetCue(cue) if cue is not None else self.CurrentCue()
		if not c:
			return self._warn("SetDelay: no such cue {!r}".format(cue))
		c['delay'] = float(seconds)
		self._build_segments()

	def SetHold(self, state, cue=None):
		"""Turn the wait-for-GO flag on/off for a cue (default: the current one)."""
		c = self.GetCue(cue) if cue is not None else self.CurrentCue()
		if not c:
			return self._warn("SetHold: no such cue {!r}".format(cue))
		c['hold'] = bool(state)

	def SetLoopStart(self, cue=None):
		"""
		Mark a cue as where OnDone() rewinds to when looping, instead of cue 1
		(default: the current cue). Only one cue should carry this - setting
		it moves the flag off every other cue.

			op.CUELIST.SetLoopStart("after_reset")
		"""
		c = self.GetCue(cue) if cue is not None else self.CurrentCue()
		if not c:
			return self._warn("SetLoopStart: no such cue {!r}".format(cue))
		for other in self.Cues:
			other['loopstart'] = (other is c)

	def LoopStart(self):
		"""The cue name OnDone() currently rewinds to when looping."""
		return self.Cues[self._loop_start() - 1]['name'] if self.Cues else None
