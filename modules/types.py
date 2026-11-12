class Any:
	def __init__(self,val=None):
		self.val = val
	def set_val(self, payload):
		self.val = payload
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return self.val
	def get_val(self):
		return self.val

class Val:
	def __init__(self,val=''):
		self.val = val
	def set_val(self, payload):
		self.val = payload["val"]
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return {"val":self.val}
	def get_val(self):
		return self.val

class Integer:
	def __init__(self,val=0):
		self.val = val
	def set_val(self, payload):
		self.val = payload.get("int")
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return {"int":self.val}
	def get_val(self):
		return self.val
		
class Float:
	def __init__(self,val=0.0):
		self.val = val
	def set_val(self, payload):
		self.val = payload.get("float")
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return {"float":self.val}
	def get_val(self):
		return self.val
		
class String:
	def __init__(self,val=""):
		self.val = val
	def set_val(self, payload):
		self.val = payload.get("string")
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return {"string":self.val}
	def get_val(self):
		return self.val
		
class Boolean:
	def __init__(self,val=False):
		self.val = val
	def set_val(self, payload):
		self.val = payload.get("bool")
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return {"bool":self.val}
	def get_val(self):
		return self.val
	
class AxesGoal:
	def __init__(self, topic="", pos=0.0, vel=0.0):
		self.topic = topic
		self.pos = pos
		self.vel = vel
	def set_val(self, payload):
		self.topic = payload.get("topic")
		self.pos = payload.get("msg").get("pos")
		self.vel = payload.get("msg").get("vel")
	def update_val(self,val):
		self.pos = val[0]
		self.vel = val[1]
	def get_dict(self):
		return '{"cmd": "publish", "topic": "%s", "ttl": 0, "msg": {"pos": %f, "vel": %f}}' % (self.topic,self.pos,self.vel)
	def get_val(self):
		return [self.topic, self.pos, self.vel]

class AxesState:
	def __init__(self, topic="", t=0.0, pos=0.0, vel=0.0, at_goal=False, state=""):
		self.topic = topic
		self.t = t
		self.pos = pos
		self.vel = vel
		self.at_goal = at_goal
		self.state = state
	def set_val(self, payload):
		self.topic = payload.get("topic")
		msg = payload.get("msg")
		self.t = msg.get("t")
		self.pos = msg.get("pos")
		self.vel = msg.get("vel")
		self.at_goal = msg.get("at_goal")
		self.state = msg.get("state")
	def update_val(self,val):
		#only receiving vals
		pass
	def get_dict(self):
		#only receiving vals
		pass
	def get_val(self):
		return [self.topic, self.t, self.pos, self.vel, self.at_goal, self.state]	
		
class Custom:
	def __init__(self,key="key", val=0):
		self.key = key
		self.val = val
	def set_val(self, payload):
		self.val = payload.get(self.key)
	def update_val(self,val):
		self.val = val
	def get_dict(self):
		return {self.key:self.val}
	def get_val(self):
		return [self.val]
	