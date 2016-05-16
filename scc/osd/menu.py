#!/usr/bin/env python2
"""
SC-Controller - OSD Menu

Display menu that user can navigate through and print chosen item id to stdout
"""
from __future__ import unicode_literals
from scc.tools import _, set_logging_level

from gi.repository import Gtk, GLib
from scc.constants import LEFT, RIGHT, STICK, STICK_PAD_MIN, STICK_PAD_MAX
from scc.tools import point_in_gtkrect
from scc.paths import get_share_path
from scc.menu_data import MenuData
from scc.gui.daemon_manager import DaemonManager
from scc.osd.timermanager import TimerManager
from scc.osd import OSDWindow

import os, sys, logging
log = logging.getLogger("osd.menu")


class Menu(OSDWindow, TimerManager):
	EPILOG="""Exit codes:
   0  - clean exit, user selected option
  -1  - clean exit, user canceled menu
   1  - error, invalid arguments
   2  - error, failed to access sc-daemon, sc-daemon reported error or died while menu is displayed.
   3  - erorr, failed to lock input stick, pad or button(s)
	"""
	REPEAT_DELAY = 0.5
	
	def __init__(self):
		OSDWindow.__init__(self, "osd-menu")
		TimerManager.__init__(self)
		self.daemon = None
		
		self.v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.v.set_name("osd-menu")
		
		cursor = os.path.join(get_share_path(), "images", 'menu-cursor.svg')
		self.cursor = Gtk.Image.new_from_file(cursor)
		self.cursor.set_name("osd-menu-cursor")
		
		self.f = Gtk.Fixed()
		self.f.add(self.v)
		self.add(self.f)
		
		self._direction = 0		# Movement direction
		self._selected = None
		self._use_cursor = False
		self._control_with = STICK
		self._confirm_with = 'A'
		self._cancel_with = 'B'
	
	
	def _add_arguments(self):
		OSDWindow._add_arguments(self)
		self.argparser.add_argument('--control-with', '-c', type=str,
			metavar="option", default=STICK, choices=(LEFT, RIGHT, STICK),
			help="which pad or stick should be used to navigate menu (default: %s)" % (STICK,))
		self.argparser.add_argument('--confirm-with', type=str,
			metavar="button", default='A',
			help="button used to confirm choice (default: A)")
		self.argparser.add_argument('--cancel-with', type=str,
			metavar="button", default='B',
			help="button used to cancel menu (default: B)")
		self.argparser.add_argument('--confirm-with-release', action='store_true',
			help="confirm choice with button release instead of button press")
		self.argparser.add_argument('--cancel-with-release', action='store_true',
			help="cancel menu with button release instead of button press")
		self.argparser.add_argument('--use-cursor', '-u', action='store_true',
			help="display and use cursor")
		self.argparser.add_argument('--from-profile', '-p', type=str,
			metavar="profile_file menu_name",
			help="load menu items from profile file")
		self.argparser.add_argument('items', type=str, nargs='+', metavar='id title',
			help="Menu items")
	
	
	def parse_argumets(self, argv):
		if not OSDWindow.parse_argumets(self, argv):
			return False
		if self.args.from_profile:
			try:
				self.items = MenuData.from_profile(self.args.from_profile, self.args.items[0])
			except IOError:
				print >>sys.stderr, '%s: error: profile file not found' % (sys.argv[0])
				return False
			except ValueError:
				print >>sys.stderr, '%s: error: menu not found' % (sys.argv[0])
				return False
		else:
			try:
				self.items = MenuData.from_args(self.args.items)
			except ValueError:
				print >>sys.stderr, '%s: error: invalid number of arguments' % (sys.argv[0])
				return False
		
		# Parse simpler arguments
		self._control_with = self.args.control_with
		self._confirm_with = self.args.confirm_with
		self._cancel_with = self.args.cancel_with
		
		if self.args.use_cursor:
			self.f.add(self.cursor)
			self.f.show_all()
			self._use_cursor = True
		
		# Create buttons that are displayed on screen
		for item in self.items:
			item.widget = Gtk.Button.new_with_label(item.label)
			self.v.pack_start(item.widget, True, True, 0)
			item.widget.set_name("osd-menu-item")
			item.widget.set_relief(Gtk.ReliefStyle.NONE)
		return True
	
	
	def select(self, index):
		if self._selected:
			self._selected.widget.set_name("osd-menu-item")
		self._selected = self.items[index]
		self._selected.widget.set_name("osd-menu-item-selected")
	
	
	def run(self):
		self.daemon = DaemonManager()
		self.daemon.connect('dead', self.on_daemon_died)
		self.daemon.connect('error', self.on_daemon_died)
		self.daemon.connect('event', self.on_event)
		self.daemon.connect('alive', self.on_daemon_connected)
		self.select(0)
		OSDWindow.run(self)
	
	
	def on_daemon_died(self, *a):
		self.quit(2)
	
	
	def on_failed_to_lock(self, error):
		log.error("Failed to lock input: %s", error)
		self.quit(3)
	
	
	def on_daemon_connected(self, *a):
		def success(*a):
			log.error("Sucessfully locked input")
			pass
		
		locks = [ self._control_with, self._confirm_with, self._cancel_with ]
		self.daemon.lock(success, self.on_failed_to_lock, *locks)
	
	
	def on_move(self):
		i = self.items.index(self._selected) + self._direction
		if i >= len(self.items):
			i = 0
		elif i < 0:
			i = len(self.items) - 1
		self.select(i)
		self.timer("move", self.REPEAT_DELAY, self.on_move)
	
	
	def on_event(self, daemon, what, data):
		if what == self._control_with:
			x, y = data
			if self._use_cursor:
				max_w = self.get_allocation().width - (self.cursor.get_allocation().width * 0.8)
				max_h = self.get_allocation().height - (self.cursor.get_allocation().height * 1.0)
				x = ((x / (STICK_PAD_MAX * 2.0)) + 0.5) * max_w
				y = (0.5 - (y / (STICK_PAD_MAX * 2.0))) * max_h
				self.f.move(self.cursor, int(x), int(y))
				for i in self.items:
					if point_in_gtkrect(i.widget.get_allocation(), x, y):
						self.select(self.items.index(i))
			else:
				if y < STICK_PAD_MIN / 3 and self._direction != 1:
					self._direction = 1
					self.on_move()
				if y > STICK_PAD_MAX / 3 and self._direction != -1:
					self._direction = -1
					self.on_move()
				if y < STICK_PAD_MAX / 3 and y > STICK_PAD_MIN / 3 and self._direction != 0:
					self._direction = 0
					self.cancel_timer("move")
		elif what == self._cancel_with:
			if data[0] == 0:	# Button released
				self.quit(-1)
		elif what == self._confirm_with:
			if data[0] == 0:	# Button released
				print self._selected.id
				self.quit(0)
		else:
			print ">>>", what
