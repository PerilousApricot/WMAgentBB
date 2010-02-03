from ConfigParser import ConfigParser
from buildbot.process import factory
from buildbot.steps.source import CVS
from buildbot.steps.shell import Compile
from buildbot.steps.python_twisted import Trial
from buildbot.steps.python import PyLint
from buildbot.steps.shell import ShellCommand, Test
from buildbot import scheduler
from buildbot.changes.mail import MaildirSource
import buildbot.steps.shell
from twisted.python import log
from email import message_from_file
from email.Utils import parseaddr
from email.Iterators import body_line_iterator
from buildbot.status.builder import SUCCESS, FAILURE, WARNINGS, SKIPPED 
from zope.interface import implements
from twisted.python import log
from buildbot import util
from buildbot.interfaces import IChangeSource
from buildbot.changes import changes
from buildbot.changes.maildir import MaildirService



c = BuildmasterConfig = {}

from buildbot.buildslave import BuildSlave
# you would add other slaves here, build-slave is a hostname
c['slaves'] = []
c['slavePortnum'] = 9989


class CMSMaildirSource(MaildirSource):
    name = "Syncmail"

    def parse(self, m, prefix=None):
        """Parse messages sent by the 'syncmail' program, as suggested by the
        sourceforge.net CVS Admin documentation. Syncmail is maintained at
        syncmail.sf.net .
        """
        # pretty much the same as freshcvs mail, not surprising since CVS is
        # the one creating most of the text

        # The mail is sent from the person doing the checkin. Assume that the
        # local username is enough to identify them (this assumes a one-server
        # cvs-over-rsh environment rather than the server-dirs-shared-over-NFS
        # model)
        name, addr = parseaddr(m["from"])
        if not addr:
            return None # no From means this message isn't from FreshCVS
        at = addr.find("@")
        if at == -1:
            who = addr # might still be useful
        else:
            who = addr[:at]

        # we take the time of receipt as the time of checkin. Not correct (it
        # depends upon the email latency), but it avoids the
        # out-of-order-changes issue. Also syncmail doesn't give us anything
        # better to work with, unless you count pulling the v1-vs-v2
        # timestamp out of the diffs, which would be ugly. TODO: Pulling the
        # 'Date:' header from the mail is a possibility, and
        # email.Utils.parsedate_tz may be useful. It should be configurable,
        # however, because there are a lot of broken clocks out there.
        when = util.now()

        subject = m["subject"]
        # syncmail puts the repository-relative directory in the subject:
        # mprefix + "%(dir)s %(file)s,%(oldversion)s,%(newversion)s", where
        # 'mprefix' is something that could be added by a mailing list
        # manager.
        # this is the only reasonable way to determine the directory name
        space = subject.rfind(" ")
        if space != -1:
            directory = subject[space + 1:]
        else:
            directory = subject

        files = []
        comments = ""
        isdir = 0
        branch = None

        lines = list(body_line_iterator(m))
        while lines:
            line = lines.pop(0)

            if (line == "Modified Files:\n" or
                line == "Added Files:\n" or
                line == "Removed Files:\n"):
                break

        while lines:
            line = lines.pop(0)
            if line == "\n":
                break
            if line == "Log Message:\n":
                lines.insert(0, line)
                break
            line = line.lstrip()
            line = line.rstrip()
            # note: syncmail will send one email per directory involved in a
            # commit, with multiple files if they were in the same directory.
            # Unlike freshCVS, it makes no attempt to collect all related
            # commits into a single message.

            # note: syncmail will report a Tag underneath the ... Files: line
            # e.g.:       Tag: BRANCH-DEVEL

            if line.startswith('Tag:'):
                branch = line.split(' ')[-1].rstrip()
                continue

            thesefiles = line.split(" ")
            for f in thesefiles:
                f = directory + "/" + f
                if prefix:
                    # insist that the file start with the prefix: we may get
                    # changes we don't care about too
                    if f.startswith(prefix):
                        f = f[len(prefix):]
                    else:
                        continue
                        break
                # TODO: figure out how new directories are described, set
                # .isdir
                files.append(f)

        if not files:
            return None

        while lines:
            line = lines.pop(0)
            if line == "Log Message:\n":
                break
        # message is terminated by "Index:..." (patch) or "--- NEW FILE.."
        # or "--- filename DELETED ---". Sigh.
        while lines:
            line = lines.pop(0)
            if line.find("Index: ") == 0:
                break
            if re.search(r"^--- NEW FILE", line):
                break
            if re.search(r" DELETED ---$", line):
                break
            comments += line
        comments = comments.rstrip() + "\n"

        change = changes.Change(who, files, comments, isdir, when=when,
                                branch=branch)

        return change



### change source for CVS 
from buildbot.changes.pb import PBChangeSource
c['change_source'] = PBChangeSource()
from buildbot.changes.mail import SyncmailMaildirSource
c['change_source'] = CMSMaildirSource('/home/meloam/.getmail/gmail-archive/wmcore', prefix = 'COMP/WMCORE/')

####
### SIMON, CAN YOU ADD YOUR CVS MESS HERE
####


### slave configuration
##TODO MAKE THIS AN EXTERNAL FILE

# track the different types of slaves by arch/distro
slaveLookup = {}
slaveLookup['sl5x86'] = ['bbslave1']
slaveLookup['sl4x86'] = ['bbslave2']
slaveLookup['sl5x86_64'] = ['bbslave3','melo-mbp-slave']

allSlaves = slaveLookup['sl5x86'] + slaveLookup['sl4x86'] + slaveLookup['sl5x86_64']
c['slaves'] = [BuildSlave('bbslave1','pass',max_builds = 1),
		BuildSlave('bbslave2','pass', max_builds = 1),
		BuildSlave('bbslave3','pass', max_builds = 1),
		BuildSlave('melo-mbp-slave','pass', max_builds = 1)]

### commmon bits for builders
cvsroot = ":pserver:anonymous@cmscvs.cern.ch:/cvs_server/repositories/CMSSW"
cvsmodule = "COMP/WMCORE"
cvs_step = CVS(cvsroot=cvsroot, cvsmodule=cvsmodule,  mode="clobber", timeout=600)
cvs_update = CVS(cvsroot=cvsroot, cvsmodule=cvsmodule,  mode="update", timeout=600)
### special builders (i.e. lint)
#src/python/PSetTweaks/__init__.py:1: [C] Missing docstring
#src/python/PSetTweaks/PSetTweak.py:95: [W, PSetLister.__call__] Used builtin function 'map'
import re
try: 
	import cStringIO 
	StringIO = cStringIO.StringIO 
except ImportError: 
	from StringIO import StringIO 


class MyPyLint(PyLint):
	_parseable_line_re = re.compile(r'[^:]+:\d+: \[%s[,\]] .+' % PyLint._msgtypes_re_str)		
	
	def __init__(self, onlyChanged=False, myCommand = None, **kwargs):
		if 'command' in kwargs:
			self.myCommand = kwargs['command']
		
		PyLint.__init__(self, **kwargs)
		self.addFactoryArguments( onlyChanged = onlyChanged,
					  myCommand = myCommand )
		self.onlyChanged = False
		if onlyChanged is not None:
			self.onlyChanged = onlyChanged
		if myCommand is not None:
			self.myCommand = myCommand

	def start(self):
		log.msg( self.build )
		files = []
		if self.build.getSourceStamp().changes:
			for c in self.build.getSourceStamp().changes:
				for fn in c.files: 
					files.append( fn )
		log.msg( "Pylinting files: %s" % files )
		log.msg( "self.onlychanged is %s" % self.onlyChanged )
		if ( (not files) and (self.onlyChanged) ):
			return SKIPPED
		
		if ( (not hasattr( self, 'myCommand')) or (self.myCommand == None )):
			return PyLint.start(self)
	
		self.setCommand( self.myCommand )
		if files and self.onlyChanged:
			log.msg("extending commandline")
			newCommand = self.myCommand + files
			self.setCommand( newCommand )
		
		PyLint.start(self)

	# todo: fix this
	# Your code has been rated at 6.82/10
fullBuilderNames = []
quickBuilderNames = ["PyLint"]
f = factory.BuildFactory()
f.addStep( cvs_update )
f.addStep(MyPyLint(flunkOnFailure=False,
		warnOnFailure=True,
	command=["pylint", "--rcfile=standards/.pylintrc", 
	"--output-format=parseable"
	],
	onlyChanged=True,
	env={'PYTHONPATH':'src/python:test/python'},
	timeout=600))

ourBuilder = { 'name': "PyLint",
		'slavenames': allSlaves,
		'builddir': 'pylint',
		'factory': f}

c['builders']  = [ourBuilder]
quickBuilders  = [ourBuilder]

### builders for different python/database combos' unittests
fullBuilders  = []

quickSetup = [ cvs_update ]
fullSetup = [ cvs_step ]

#fullBuilderNames.append("Full PyLint")
f = factory.BuildFactory()
f.addStep( cvs_update )
f.addStep(MyPyLint(flunkOnFailure=False,
		warnOnFailure=True,
	command=["pylint", "--rcfile=standards/.pylintrc", 
	"--output-format=parseable",
	"src/python/IMProv",
	"src/python/PSetTweaks",
	"src/python/WMComponent",
	"src/python/WMCore",
	"src/python/WMQuality",
	"test/python/PSetTweaks_t",
	"test/python/WMComponent_t",
	"test/python/WMCore_t",
	"standards/"
	],
	env={'PYTHONPATH':'src/python:test/python'},
	timeout=1200))

ourBuilder = { 'name': "Full PyLint",
		'slavenames': allSlaves,
		'builddir': 'pylint-full',
		'factory': f}
c['builders'].append(ourBuilder)
#fullBuilders.append(ourBuilder)

f = factory.BuildFactory()
f.addStep( cvs_step )
f.addStep(ShellCommand(command=["code coverage"],
				env={'PYTHONPATH':'src/python:test/python'}))
ourBuilder2 = { 'name': "Code Coverage",
		'slavenames': allSlaves,
		'builddir': 'coverage',
		'factory': f }

c['builders'].append(ourBuilder2)


# make a quick-test that will run on mysql/python2.6
#   we can run it more quickly to give devs better feedback
f = factory.BuildFactory()
f.addSteps( quickSetup )

class MyTest(buildbot.steps.shell.Test):
	def createSummary(self, log):
		# Stats: 168 successful, 0 failures, 20 errors, 105 didn't run
		ourRe = re.compile(r'Stats: (\d+) successful, (\d+) failures, (\d+) errors, (\d+) didn\'t run')
		self.descriptionDone = []
		for line in StringIO(log.getText()).readlines():
			result = ourRe.match(line)
			if result:
				(mySuccess, myFail, myErrors, myNorun) =\
					result.group(1,2,3,4)
				self.descriptionDone.append("Succeeded=%s"%mySuccess)
				self.descriptionDone.append("Failed=%s"%myFail)
				self.descriptionDone.append("Errored=%s"%myErrors)
				self.descriptionDone.append("BadLoad=%s"%myNorun)
				self.setProperty("test-succeeded", mySuccess)
				self.setProperty("test-failed", myFail)
				self.setProperty("test-errored", myErrors)
				self.setProperty("test-badload", myNorun)


f.addStep(MyTest(command=['python',"standards/wrapEnv.py",'python26', 'mysql','python2.6','setup.py', 'test']))
ourBuilder = { 'name': "Quick Test",
		'slavenames': slaveLookup["sl5x86_64"],
		'builddir': 'quicktest',
		'factory': f ,
		'env':{'PYTHONPATH':['src/python','test/python']}}
quickBuilderNames.append("Quick Test")



c['builders'].append(ourBuilder)
pymap = {'python24':'python2.4', 'python26':'python2.6'}
for x in [ { 'name': 'py24-mysql', 'python': 'python24', 'db': 'mysql'},
	     { 'name': 'py24-oracle','python': 'python24', 'db': 'oracle'},
	     { 'name': 'py24-sqlite', 'python': 'python24', 'db': 'sqlite'},
             { 'name': 'py26-mysql', 'python': 'python26', 'db': 'mysql'},
	     { 'name': 'py26-oracle', 'python': 'python26', 'db': 'oracle'},
	     { 'name': 'py26-sqlite', 'python': 'python26', 'db': 'sqlite'} ]:
	for y in [ {'name': 'sl5x86', 'distro': 'sl5', 'arch': 'x86' },
		   {'name': 'sl4x86', 'distro': 'sl4', 'arch': 'x86' },
		   {'name': 'sl5x86_64', 'distro': 'sl5', 'arch': 'x86_64'} ]:
		## lot of combinations of builders, yesh
		f = factory.BuildFactory()
		f.addSteps( fullSetup )
		f.addStep(ShellCommand(command=['python','-vv']))
		f.addStep(MyTest(command=['python',"standards/wrapEnv.py", x['python'], x['db'], pymap[x['python']],'setup.py','test'],
					env={'PYTHONPATH':['./src/python:./test/python']}))
		fullBuilderNames.append("Full Tests %s-%s" % (x['name'],y['name']))
		ourBuilder = { 'name': "Full Tests %s-%s" % (x['name'],y['name']),
				'slavenames': slaveLookup["%s%s" % (y['distro'],y['arch'])],
				'builddir': 'full-%s-%s-%s-%s' %(y['distro'], y['arch'], x['python'], x['db']),
				'factory': f}
		fullBuilders.append(ourBuilder)
		c['builders'].append(ourBuilder)




### schedulers
c['schedulers'] = []
###  nightly
print fullBuilderNames
nightlySched = scheduler.Nightly(name = 'nightly', 
					hour=3,
					onlyIfChanged=True,
					builderNames=fullBuilderNames)
c['schedulers'].append(nightlySched)
###  5 min post-commit
quickBuild = scheduler.Scheduler( name="quick",branch=None,
				  treeStableTimer=60*5,
				  builderNames=quickBuilderNames)
c['schedulers'].append(quickBuild)
### 30 min post commit
fullBuild = scheduler.Scheduler( name="full",branch=None,
				treeStableTimer=30*60,
				builderNames=fullBuilderNames )
c['schedulers'].append(fullBuild)

### post-nightly coverage tests
from buildbot import scheduler
package = scheduler.Dependent("build-package",
				nightlySched, # upstream scheduler -- no quotes!
				 ["Code Coverage"])

### status updates
c['status'] = []
from buildbot.status.html import WebStatus 
# Uncomment the following when impatient.... 
users = [('melo','melo')]

from buildbot.status.web.auth import BasicAuth 
c['status'].append(WebStatus(http_port=8010, allowForce=True, auth=BasicAuth(users)))

c['projectName'] = "WMAgent"
c['projectURL'] = "http://cms.cern.ch/"
c['buildbotURL'] = "http://vpac08.phy.vanderbilt.edu:8010/"
