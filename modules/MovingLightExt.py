"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki


MovingLightExt
--------------
Estimates the world position of a moving light from a set of known target
points and the pan value the fixture used to aim at each of them.

Each observation gives us: "when panned to angle a_i, the fixture points at
world point T_i". The horizontal bearing from the (unknown) fixture position
P to T_i therefore equals a_i + offset. That means P lies on the line through
T_i whose direction is the reverse of that bearing. With two or more targets
these lines intersect at P; with more (and noise) we take the point that is
closest to all of them in a least-squares sense.

Pan only constrains the horizontal plane, so the Z of the estimate is just
the mean Z of the target points (best planar guess).

Inputs are two CHOPs that must live directly inside this component:

	target_positions - one sample per target, channels x / y (and optionally
	                   z). tx / ty / tz are also accepted.
	target_dmxvals   - one sample per target, first channel = the pan ANGLE
	                   in degrees (-270..270) used for that target.

Relevant custom parameters (all optional, sensible defaults used if absent):

	Panoffset  fixed offset in degrees between pan-zero and world-zero bearing
	Paninvert  reverse the pan direction
	Solveoffset  also solve for Panoffset automatically (recommended)
	Iterations   iterations for the alternating position/offset solve
"""

import csv
import math

try:
	import numpy as np
except ImportError:
	np = None

from TDStoreTools import StorageManager
import TDFunctions as TDF


class MovingLightExt:
	"""
	MovingLightExt description
	"""
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		# results, written by Solve()
		TDF.createProperty(self, 'EstimatedPosition', value=[.0,.0,.0],
						   dependable=True, readOnly=False)
		TDF.createProperty(self, 'EstimateResidual', value=None,
						   dependable=True, readOnly=False)
		TDF.createProperty(self, 'SolvedPanOffset', value=.0,
						   dependable=True, readOnly=False)
		# 1000 x [R, G, B, W, Gobo] lookup table, index = pan normalised -180..180 -> 0..1
		TDF.createProperty(self, 'ColorLUT', value=[],
						   dependable=True, readOnly=False)
						   
		self.EstimatePosition()

	# index positions of the four rectangle corners in the target sample order
	CORNER_INDICES = (0, 3, 6, 9)

	# ------------------------------------------------------------------ #
	#  input properties                                                   #
	# ------------------------------------------------------------------ #

	@property
	def TargetPositions(self):
		"""CHOP inside the comp holding one xy(z) sample per target point."""
		return self.ownerComp.op('target_positions')

	@property
	def TargetDMXVals(self):
		"""CHOP inside the comp holding one pan angle (deg) per target point."""
		return self.ownerComp.op('target_dmxvals')

	# ------------------------------------------------------------------ #
	#  parameter helpers                                                  #
	# ------------------------------------------------------------------ #

	def _par(self, name, default):
		par = getattr(self.ownerComp.par, name, None)
		if par is None:
			return default
		try:
			return par.eval()
		except Exception:
			return default

	def _panToBearingDegrees(self, panDeg):
		"""
		Map the fixture pan angle (already in degrees, e.g. -270..270) to a
		world-relative horizontal bearing in degrees.
		"""
		offset = float(self._par('Panoffset', 0.0))
		invert = -1.0 if self._par('Paninvert', False) else 1.0
		return offset + invert * panDeg

	# ------------------------------------------------------------------ #
	#  CHOP reading                                                       #
	# ------------------------------------------------------------------ #

	@staticmethod
	def _channel(chop, names):
		for n in names:
			ch = chop.chan(n)
			if ch is not None:
				return np.array(ch.vals, dtype=float)
		return None

	def _readTargets(self):
		"""Return (pts Nx3, panDeg N) as numpy arrays, or raise ValueError."""
		posChop = self.TargetPositions
		dmxChop = self.TargetDMXVals
		if posChop is None:
			raise ValueError('TargetPositions CHOP not found')
		if dmxChop is None:
			raise ValueError('TargetDMXVals CHOP not found')

		xs = self._channel(posChop, ['x', 'tx', 'posx', 'X'])
		ys = self._channel(posChop, ['y', 'ty', 'posy', 'Y'])
		zs = self._channel(posChop, ['z', 'tz', 'posz', 'Z'])
		if xs is None or ys is None:
			raise ValueError("TargetPositions needs 'x' and 'y' channels")
		if zs is None:
			zs = np.zeros_like(xs)

		if len(dmxChop.chans()) == 0:
			raise ValueError('TargetDMXVals has no channels')
		pan = np.array(dmxChop.chans()[0].vals, dtype=float)

		n = min(len(xs), len(ys), len(zs), len(pan))
		if n < 2:
			raise ValueError('need at least 2 target points, got %d' % n)

		pts = np.column_stack([xs[:n], ys[:n], zs[:n]])
		return pts, pan[:n]

	# ------------------------------------------------------------------ #
	#  geometry                                                           #
	# ------------------------------------------------------------------ #

	@staticmethod
	def _closestPointToLines(points, dirs):
		"""
		Least-squares point closest to a set of 3D lines.
		Line i passes through points[i] with unit direction dirs[i].
		Minimises sum ||(I - d d^T)(P - a)||^2  ->  (sum M_i) P = sum M_i a_i
		"""
		A = np.zeros((3, 3))
		b = np.zeros(3)
		eye = np.eye(3)
		for a, d in zip(points, dirs):
			d = d / (np.linalg.norm(d) or 1.0)
			m = eye - np.outer(d, d)
			A += m
			b += m @ a
		P = np.linalg.lstsq(A, b, rcond=None)[0]
		# rms perpendicular distance
		res = 0.0
		for a, d in zip(points, dirs):
			d = d / (np.linalg.norm(d) or 1.0)
			v = P - a
			perp = v - np.dot(v, d) * d
			res += float(np.dot(perp, perp))
		rms = math.sqrt(res / len(points))
		return P, rms

	@staticmethod
	def _horizontalDirs(anglesDeg):
		a = np.radians(anglesDeg)
		return np.column_stack([np.cos(a), np.sin(a), np.zeros_like(a)])

	@staticmethod
	def _circmean(anglesRad):
		return math.atan2(float(np.mean(np.sin(anglesRad))),
						  float(np.mean(np.cos(anglesRad))))

	# ------------------------------------------------------------------ #
	#  main entry points                                                  #
	# ------------------------------------------------------------------ #

	def EstimatePosition(self):
		"""
		Compute and return the position estimate as a tdu.Position.
		Also updates EstimatedPosition / EstimateResidual / SolvedPanOffset.
		Returns None if the inputs are not usable.
		"""
		if np is None:
			raise ImportError('numpy is required for MovingLightExt')

		pts, panDeg = self._readTargets()
		baseDeg = self._panToBearingDegrees(panDeg)      # world bearing, no auto offset
		extraOffset = 0.0

		iterations = int(self._par('Iterations', 30))
		solveOffset = bool(self._par('Solveoffset', True))

		dirs = self._horizontalDirs(baseDeg)
		P, rms = self._closestPointToLines(pts, dirs)

		if solveOffset:
			for _ in range(max(1, iterations)):
				# bearing from current estimate to each target (xy only)
				dx = pts[:, 0] - P[0]
				dy = pts[:, 1] - P[1]
				bearing = np.arctan2(dy, dx)
				modelled = np.radians(baseDeg + math.degrees(extraOffset))
				delta = self._circmean(bearing - modelled)
				if abs(delta) < 1e-9:
					break
				extraOffset += delta
				dirs = self._horizontalDirs(baseDeg + math.degrees(extraOffset))
				P, rms = self._closestPointToLines(pts, dirs)

		# Z is unobservable from pan alone -> mean of target Z
		P[2] = float(np.mean(pts[:, 2]))

		totalOffset = float(self._par('Panoffset', 0.0)) + math.degrees(extraOffset)
		self.EstimatedPosition = tuple(float(v) for v in P)
		self.EstimateResidual = float(rms)
		self.SolvedPanOffset = totalOffset

		return tdu.Position(float(P[0]), float(P[1]), float(P[2]))

	# ------------------------------------------------------------------ #
	#  colour lookup table                                                #
	# ------------------------------------------------------------------ #

	@staticmethod
	def _unwrapDegrees(seq):
		"""Make a sequence of angles continuous (no +/-180 jumps)."""
		out = [float(seq[0])]
		for v in seq[1:]:
			prev = out[-1]
			d = (float(v) - prev + 180.0) % 360.0 - 180.0
			out.append(prev + d)
		return out

	def BuildColorLUT(self, n=1000, path=None):
		"""
		Build an n-sample x 5-channel [R, G, B, W, Gobo] lookup table from
		target_dmx_vals (pan angle per target) and output_dmx_vals (the
		matching R/G/B/W/Gobo per target). R/G/B hold the north-wall whites;
		the dedicated W channel holds the west-wall whites (R=G=B=0).

		Sample k corresponds to pan angle  -180 + 360*k/(n-1)  degrees, i.e.
		look it up later with  norm = (pan + 180) / 360  ->  index = norm*(n-1).

		The targets sit on the walls of a rectangle, so pan angle is not
		linear with position along a wall. Within each wall (the span between
		two corner targets) interpolation is done in tan(angle - wallCenter)
		space - the arctan/perspective-correct mapping for a flat surface -
		instead of linearly in the angle.

		The LUT is written to a CSV file (columns: index, pan_deg, norm, R, G,
		B, W, Gobo). The path is the `path` argument, else the 'Lutfile' custom
		parameter, else <project folder>/<comp name>_color_lut.csv. Returns the
		absolute file path; the list is also kept in self.ColorLUT.
		"""
		panChop = self.TargetDMXVals
		colChop = self.ownerComp.op('output_dmx_vals')
		if panChop is None:
			raise ValueError('target_dmx_vals CHOP not found')
		if colChop is None:
			raise ValueError('output_dmx_vals CHOP not found')

		pan = [float(v) for v in panChop.chans()[0].vals]
		rgbwg = []
		for name in ('r', 'g', 'b', 'w', 'gobo'):
			ch = colChop.chan(name)
			if ch is None:
				raise ValueError("output_dmx_vals needs an '%s' channel" % name)
			rgbwg.append([float(v) for v in ch.vals])
		m = len(pan)
		colors = [[rgbwg[c][i] for c in range(len(rgbwg))] for i in range(m)]

		lut = self._buildColorLUT(pan, colors, n, self.CORNER_INDICES)
		self.ColorLUT = lut

		if not path:
			path = self._par('Lutfile', '')
		if not path:
			path = '{}/{}_color_lut.csv'.format(project.folder, self.ownerComp.name)
		path = tdu.expandPath(path)
		with open(path, 'w', newline='') as f:
			wr = csv.writer(f)
			wr.writerow(['index', 'pan_deg', 'norm', 'R', 'G', 'B', 'W', 'Gobo'])
			for k, row in enumerate(lut):
				panDeg = -180.0 + 360.0 * k / (n - 1)
				wr.writerow([k, round(panDeg, 4), round((panDeg + 180.0) / 360.0, 6)]
							+ [round(v, 6) for v in row])
		return path

	@classmethod
	def _buildColorLUT(cls, panDeg, colors, n, corners):
		m = len(panDeg)
		cont = cls._unwrapDegrees(panDeg)
		direction = -1.0 if (cont[-1] - cont[0]) < 0 else 1.0
		cont.append(cont[0] + direction * 360.0)          # close the loop
		cols = [list(c) for c in colors] + [list(colors[0])]
		cidx = list(corners) + [m]

		# per wall: (minAngle, maxAngle, wallCenter, anchorIndices, tanCoords)
		walls = []
		for w in range(len(cidx) - 1):
			i0, i1 = cidx[w], cidx[w + 1]
			center = 0.5 * (cont[i0] + cont[i1])
			idxs = list(range(i0, i1 + 1))
			us = [math.tan(math.radians(cls._clamp(cont[i] - center, -89.5, 89.5)))
				  for i in idxs]
			walls.append((min(cont[i0], cont[i1]), max(cont[i0], cont[i1]),
						  center, idxs, us))

		lo, hi = min(cont[0], cont[-1]), max(cont[0], cont[-1])
		lut = []
		for k in range(n):
			q = -180.0 + 360.0 * k / (n - 1)
			while q < lo:
				q += 360.0
			while q > hi:
				q -= 360.0
			wall = None
			for wl in walls:
				if wl[0] - 1e-6 <= q <= wl[1] + 1e-6:
					wall = wl
					break
			if wall is None:
				wall = walls[0] if q <= walls[0][0] else walls[-1]
			_, _, center, idxs, us = wall
			uq = math.tan(math.radians(cls._clamp(q - center, -89.5, 89.5)))
			inc = us[-1] >= us[0]
			seg = None
			for s in range(len(idxs) - 1):
				a, b = us[s], us[s + 1]
				if (inc and a <= uq <= b) or ((not inc) and b <= uq <= a):
					seg = s
					break
			if seg is None:
				seg = 0 if ((inc and uq < us[0]) or ((not inc) and uq > us[0])) \
					  else len(idxs) - 2
			a, b = us[seg], us[seg + 1]
			t = 0.0 if b == a else cls._clamp((uq - a) / (b - a), 0.0, 1.0)
			ca, cb = cols[idxs[seg]], cols[idxs[seg + 1]]
			lut.append([ca[j] + t * (cb[j] - ca[j]) for j in range(len(ca))])
		return lut

	@staticmethod
	def _clamp(v, lo, hi):
		return lo if v < lo else hi if v > hi else v

	def LookupColor(self, pan):
		"""Sample the stored ColorLUT at a pan angle in degrees (-180..180)."""
		lut = self.ColorLUT
		if not lut:
			lut = self.BuildColorLUT()
		pan = self._clamp(((float(pan) + 180.0) % 360.0) - 180.0, -180.0, 180.0)
		f = (pan + 180.0) / 360.0 * (len(lut) - 1)
		i = int(f)
		if i >= len(lut) - 1:
			return list(lut[-1])
		frac = f - i
		a, b = lut[i], lut[i + 1]
		return [a[j] + frac * (b[j] - a[j]) for j in range(len(a))]

	def Solve(self):
		"""
		Recompute the position estimate. Results land in the dependable
		properties EstimatedPosition / EstimateResidual / SolvedPanOffset.
		"""
		return self.EstimatePosition()
