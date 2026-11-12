"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component.

SystemExt - OS-level lifecycle for the machina Raspberry Pis, over SSH.

This is the RECOVERY path: reboot / shutdown work whenever sshd + the network
are up, even when the machina process has crashed - which is exactly when
SupervisorExt (supervisord XML-RPC) and the MQTT bridge cannot help.

Per-process control (restart just `main`) still belongs in SupervisorExt.
Use RestartService() here only when you want the whole systemd unit bounced.

One-time setup (see the notes at the bottom of this file):
  * Windows OpenSSH client on PATH           - built into Win10/11
  * a passphrase-less key trusted by every Pi
  * NOPASSWD sudo for reboot / poweroff on each Pi
"""

import os
import subprocess

# --- fleet fallback (used when there is no 'machinas' table DAT) -------------
# name -> ip, straight from configs/DIA.json  Controller.machinas
FLEET = {
	"A-1": "10.0.0.11", "A-2": "10.0.0.12",
	"B-1": "10.0.0.21", "B-2": "10.0.0.22", "B-3": "10.0.0.23",
	"C-1": "10.0.0.31", "C-2": "10.0.0.32",
	"D-1": "10.0.0.41", "D-2": "10.0.0.42", "D-3": "10.0.0.43", "D-4": "10.0.0.44",
}

# --- ssh -------------------------------------------------------------------
SSH_USER = "pi"
SSH_KEY  = os.path.expanduser(r"~\.ssh\machina")   # the unattended private key

SSH_OPTS = [
	"-i", SSH_KEY,
	"-l", SSH_USER,
	"-o", "BatchMode=yes",                 # never prompt for a password - fail instead
	"-o", "StrictHostKeyChecking=accept-new",
	"-o", "ConnectTimeout=5",
]

# full paths so a tight sudoers rule matches. Verify with `which reboot poweroff systemctl`
# on the Pi and adjust if your image differs (bullseye puts systemctl in /bin).
CMD_REBOOT   = "sudo /sbin/reboot"
CMD_SHUTDOWN = "sudo /sbin/poweroff"
CMD_RESTART  = "sudo /usr/bin/systemctl restart machina"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no cmd flash on Windows


class SystemExt:
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.Log = op("logger")

	# -- fleet ----------------------------------------------------------

	def _fleet(self):
		"""{name: ip}. A 'machinas' table DAT (header row: name  ip) wins;
		otherwise the FLEET constant above."""
		dat = op("machinas")
		if dat is not None and dat.numRows > 1:
			return {dat[r, "name"].val: dat[r, "ip"].val for r in range(1, dat.numRows)}
		return dict(FLEET)

	def _hosts(self, target):
		"""Resolve a group name / ip / list / 'all' to a list of ip strings."""
		fleet = self._fleet()
		if target in (None, "all", "*"):
			return list(fleet.values())
		if isinstance(target, (list, tuple)):
			out = []
			for t in target:
				out += self._hosts(t)
			return out
		if target in fleet:                       # group name, e.g. "B-2"
			return [fleet[target]]
		if "." in str(target):                    # already an ip
			return [str(target)]
		self._warn("unknown machina {!r} (known: {})".format(
			target, ", ".join(sorted(fleet))))
		return []

	# -- transport ----------------------------------------------------

	def _ssh(self, host, remote_cmd):
		"""Fire-and-forget. ssh returns in ~1 s (systemd backgrounds the action),
		so this never blocks the cook; there is no reply to wait for."""
		argv = ["ssh"] + SSH_OPTS + [host, remote_cmd]
		try:
			subprocess.Popen(argv, stdout=subprocess.DEVNULL,
			                 stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
			self._info("{}  <-  {}".format(host, remote_cmd))
		except FileNotFoundError:
			self._warn("ssh.exe not found - install the Windows OpenSSH client")

	def _fanout(self, target, remote_cmd):
		hosts = self._hosts(target)
		for h in hosts:
			self._ssh(h, remote_cmd)
		return hosts

	def _info(self, t):
		(self.Log.Info if self.Log else print)("System: " + t)

	def _warn(self, t):
		(self.Log.Warning if self.Log else print)("System: " + t)

	# -- public verbs ----------------------------------------------

	def Reboot(self, target="all"):
		"""Reboot a machina ('A-1'), an ip, a list of those, or every one ('all').
		Each comes back on its own once it is up."""
		return self._fanout(target, CMD_REBOOT)

	def Shutdown(self, target="all", confirm=False):
		"""Power down. The Pi will NOT come back until mains power returns - use
		this only for the evening cut-off. `confirm=True` is required so it cannot
		fire from a stray expression, scene trigger or fat-fingered button."""
		if not confirm:
			return self._warn("Shutdown needs confirm=True")
		return self._fanout(target, CMD_SHUTDOWN)

	def RestartService(self, target="all"):
		"""Bounce the machina systemd unit (soft - no OS reboot)."""
		return self._fanout(target, CMD_RESTART)

	def Run(self, target, remote_cmd):
		"""Escape hatch: run an arbitrary command on the target(s)."""
		return self._fanout(target, remote_cmd)

	# -- one-time setup ----------------------------------------------

	def CreateKey(self):
		"""
		Generate the unattended SSH key (SSH_KEY) if it doesn't already exist.
		Local-only - the same ssh-keygen step scripts\\install-ssh-keys.ps1 does,
		callable from TD instead of PowerShell. The key still needs authorising
		on each Pi afterwards - see ONE-TIME SETUP at the bottom of this file.
		"""
		if os.path.exists(SSH_KEY):
			return self._info("key already exists: {}".format(SSH_KEY))
		os.makedirs(os.path.dirname(SSH_KEY), exist_ok=True)
		argv = ["ssh-keygen", "-t", "ed25519", "-f", SSH_KEY, "-N", "", "-C", "axial-flow-control"]
		try:
			subprocess.run(argv, check=True, creationflags=_NO_WINDOW)
			self._info("created key: {}".format(SSH_KEY))
		except FileNotFoundError:
			self._warn("ssh-keygen not found - install the Windows OpenSSH client")
		except subprocess.CalledProcessError as e:
			self._warn("ssh-keygen failed ({})".format(e.returncode))


# ===========================================================================
# ONE-TIME SETUP
# ===========================================================================
#
# 1. Windows OpenSSH client (built in; check with `ssh -V`). If missing:
#      Settings -> Optional features -> Add -> "OpenSSH Client"	
#
# 2. Create the unattended key - any ONE of these (all equivalent, idempotent -
#    skip entirely and step 3 below will create it for you too):
#      PS> ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\machina" -N '""' -C "axial-flow-control"
#      -- or, from TD once SYSTEM is wired up (step 5) --
#      op('SYSTEM').CreateKey()
#    (press Enter twice if it prompts for a passphrase - -N '""' asks for none)
#
# 3. Authorise that key on the whole fleet - run from Windows PowerShell:
#      PS> cd <axial-flow>\scripts
#      PS> .\install-ssh-keys.ps1            # asks for the mach1na password once per Pi
#
# 4. Passwordless sudo for reboot / poweroff / service-restart - PowerShell again:
#      PS> .\provision-sudo.ps1              # asks for mach1na once per Pi
#    This writes /etc/sudoers.d/machina-power on each Pi, scoped to exactly
#    those three commands. It is NOT part of the WSL rsync deploy (rsync syncs
#    files into ~/pi, it can't place a root-owned file under /etc). For a new
#    Pi later:  .\provision-sudo.ps1 -Only <name>
#
#    Both scripts are idempotent and take -Only A-1,B-2 to target a subset.
#    The fleet list lives in scripts\_fleet.ps1 (mirror of FLEET above and
#    configs/DIA.json).
#
# 5. TD wiring:
#      - Base COMP "SYSTEM"; parameter Extension 1 = op('./SystemExt'), Promote on.
#      - an op('logger') reachable from it (same one ControllerExt uses).
#      - optional: a Table DAT "machinas" (header: name  ip) to override FLEET.
#
# Usage:
#      op('SYSTEM').CreateKey()              # one-time: generate the local key
#      op('SYSTEM').Reboot('A-1')
#      op('SYSTEM').Reboot()                 # whole fleet
#      op('SYSTEM').RestartService('B-2')
#      op('SYSTEM').Shutdown(confirm=True)   # evening power-down, whole fleet
#
# Evening auto-shutdown: have SCHEDULER call op('SYSTEM').Shutdown(confirm=True)
# at the cut-off time.
# ===========================================================================
