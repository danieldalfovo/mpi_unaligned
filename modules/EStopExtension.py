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
# EStopExtension  -  poll an e-stop endpoint from a Timer CHOP
#
# Check() fires the POST; the reply arrives async on OnResponse(), which sets
# the Estop property. Read op('...').Estop for the current state.
#
# WIRING
#   - op('webclient1'): a Web Client DAT/COMP.
#   - its Callbacks DAT:
#         def onResponse(webClientDAT, statusCode, headerDict, data):
#             parent().OnResponse(statusCode, data)
#   - custom par Url (string) on this COMP: the target server, e.g.
#     "http://10.0.0.5:8080"
#   - a Timer CHOP (op('timer1')) whose Callbacks DAT calls parent().Check()
#     on whichever cycle should poll, e.g.:
#         def onCycleStart(timerOp, cycle, cycleTime):
#             parent().Check()
# ===========================================================================

class EStopExtension:
	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp
		self.Client = op('webclient1')
		self.Logger = op('logger')

		TDF.createProperty(self, 'Estop', value=True, dependable=True, readOnly=False)
		TDF.createProperty(self, 'Connected', value=False, dependable=True, readOnly=False)

		self.timer = op('timer1')
		self.timer.par.initialize.pulse()
		self.timer.par.start.pulse()

		self.port_id = 1

		self._info("initialized, polling port {} on {}".format(self.port_id, self.Client.par.url.eval()))

	def _info(self, text):
		(self.Logger.Info if self.Logger else print)("EStop: " + text)

	def _warn(self, text):
		(self.Logger.Warning if self.Logger else print)("EStop: " + text)

	def Check(self):
		"""POST the e-stop check. Wire a Timer CHOP's callback to this - the
		reply (via OnResponse) is what actually sets Estop. Connected drops to
		False here and only goes back True once a reply actually arrives, so
		it reads False for the whole round trip of a request that never comes
		back (device down, network issue, etc)."""
		self.Connected = False
		endpoint = self.Client.par.url.eval()
		method = 'POST'
		header = {"Content-Type": "application/json"}
		data = json.dumps({"apiVersion":"1.0","context":"poll","method":"getPorts","params":{"ports":[{"port":self.port_id}]}})

		authType = "digest"
		username = "diaav"
		password = "diaav"

		try:
			self.Client.request(endpoint, method, header=header, data=data, authType=authType, username=username, password=password)
		except Exception as e:
			self._warn("Check: couldn't send request to {}: {}".format(endpoint, e))

	def OnResponse(self, statusCode, data):
		"""Wire to webclient1's Callbacks DAT (onResponse). Sets Estop from
		the reply; leaves it unchanged if the request failed or didn't parse.

		The device has no single 'estop' field - it reports every port's
		current state vs its wired-normal state. Our stop button is a
		normally-closed input (port_id): state == normalState means the
		circuit is intact (not stopped); anything else - pressed, or the
		wire cut - means stopped. That's the fail-safe point of wiring it NC."""
		if statusCode['code'] != 200:
			return self._warn("OnResponse: {} {}".format(statusCode.get('code'), statusCode.get('message')))

		if not self.Connected:
			self._info("connected")
		self.Connected = True

		try:
			items = json.loads(data)['data']['items']
			port = next(p for p in items if p['port'] == str(self.port_id))
			estop = port['state'] != port['normalState']
		except Exception as e:
			return self._warn("OnResponse: couldn't parse reply: {}".format(e))

		if estop != self.Estop:
			(self._warn if estop else self._info)("estop {}".format('TRIPPED' if estop else 'cleared'))
		self.Estop = estop
