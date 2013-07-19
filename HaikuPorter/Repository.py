# -*- coding: utf-8 -*-
#
# Copyright 2013 Oliver Tappe
# Distributed under the terms of the MIT License.

# -- Modules ------------------------------------------------------------------

from HaikuPorter.Configuration import Configuration
from HaikuPorter.Port import Port
from HaikuPorter.RecipeTypes import Status
from HaikuPorter.Utils import (versionCompare, touchFile)

import glob
import os
import re
import shutil
import sys


# -- Repository class ---------------------------------------------------------

class Repository(object):
	def __init__(self, treePath, packagesPath, shellVariables, policy,
				 preserveFlags, quiet = False):
		self.treePath = treePath
		self.path = self.treePath + '/repository'
		self.packagesPath = packagesPath
		self.shellVariables = shellVariables
		self.policy = policy
		self.quiet = quiet

		# update repository if it exists and isn't empty, populate it otherwise
		if (os.path.isdir(self.path)
			and os.listdir(self.path)):
			self._updateRepository()
		else:
			self._populateRepository(preserveFlags)

	def getPortIdForPackageId(self, packageId):
		"""return the port-ID for the given package-ID"""

		# cut out subparts from the package name until we find a port
		# with that name:
		(portName, version) = packageId.rsplit('-', 1)
		(portName, unused1, unused2) = portName.rpartition('_')
		while portName:
			portID = portName + '-' + version
			if portID in self._allPorts:
				return portID
			(portName, unused1, unused2) = portName.rpartition('_')

		# no corresponding port-ID was found
		return None

	def getAllPorts(self):
		if not hasattr(self, '_allPorts'):
			self._initAllPorts()
		return self._allPorts

	def getPortVersionsByName(self):
		if not hasattr(self, '_portVersionsByName'):
			self._initAllPorts()
		return self._portVersionsByName

	def searchPorts(self, regExp):
		"""Search for one or more ports in the HaikuPorts tree, returning
		   a list of found matches"""
		if regExp:
			reSearch = re.compile(regExp)

		ports = []
		portNames = self.getPortVersionsByName().keys()
		for portName in portNames:
			if not regExp or reSearch.search(portName):
				ports.append(portName)

		return sorted(ports)

	def _initAllPorts(self):
		# For now, we collect all ports into a dictionary that can be keyed
		# by name + '-' + version. Additionally, we keep a sorted list of
		# available versions for each port name.
		self._allPorts = {}
		self._portVersionsByName = {}
		for category in sorted(os.listdir(self.treePath)):
			categoryPath = self.treePath + '/' + category
			if (not os.path.isdir(categoryPath) or category[0] == '.'
				or '-' not in category):
				continue
			for port in sorted(os.listdir(categoryPath)):
				portPath = categoryPath + '/' + port
				if not os.path.isdir(portPath) or port[0] == '.':
					continue
				for recipe in os.listdir(portPath):
					recipePath = portPath + '/' + recipe
					if (not os.path.isfile(recipePath)
						or not recipe.endswith('.recipe')):
						continue
					portElements = recipe[:-7].split('-')
					if len(portElements) == 2:
						name, version = portElements
						if name not in self._portVersionsByName:
							self._portVersionsByName[name] = [ version ]
						else:
							self._portVersionsByName[name].append(version)
						self._allPorts[name + '-' + version] \
							= Port(name, version, category, portPath,
								   self.shellVariables, self.policy)
					else:
						# invalid argument
						if not self.quiet:
							print("Warning: Couldn't parse port/version info: "
								  + recipe)

		# Sort version list of each port
		for portName in self._portVersionsByName.keys():
			self._portVersionsByName[portName].sort(cmp=versionCompare)

	def _populateRepository(self, preserveFlags):
		"""Remove and refill the repository with all PackageInfo-files from
		   parseable recipes"""

		if os.path.exists(self.path):
			shutil.rmtree(self.path)
		newRepositoryPath = self.path + '.new'
		if os.path.exists(newRepositoryPath):
			shutil.rmtree(newRepositoryPath)
		os.mkdir(newRepositoryPath)
		skippedDir = newRepositoryPath + '/.skipped'
		os.mkdir(skippedDir)
		if not self.quiet:
			print 'Populating repository ...'

		allPorts = self.getAllPorts()
		for portName in sorted(self._portVersionsByName.keys(), key=str.lower):
			for version in reversed(self._portVersionsByName[portName]):
				portID = portName + '-' + version
				port = allPorts[portID]
				try:
					if not self.quiet:
						sys.stdout.write(' ' * 60)
						sys.stdout.write('\r\t%s' % port.versionedName)
						sys.stdout.flush()
					port.parseRecipeFile(False)
					status = port.getStatusOnTargetArchitecture()
					if (status == Status.STABLE
						or (status == Status.UNTESTED
							and Configuration.shallAllowUntested())):
						if (port.checkFlag('build')
							and not preserveFlags):
							if not self.quiet:
								print '   [build-flag reset]'
							port.unsetFlag('build')
						else:
							if not self.quiet:
								print
						port.writePackageInfosIntoRepository(newRepositoryPath)
						break
					else:
						# take notice of skipped recipe file
						touchFile(skippedDir + '/' + portID)
						if not self.quiet:
							print((' is skipped, as it is %s on target '
								  + 'architecture') % status)
				except SystemExit:
					# take notice of broken recipe file
					touchFile(skippedDir + '/' + portID)
					if not self.quiet:
						sys.stdout.write('\r')
					pass
		os.rename(newRepositoryPath, self.path)

	def _updateRepository(self):
		"""Update all PackageInfo-files in the repository as needed"""

		allPorts = self.getAllPorts()

		brokenPorts = []

		# check for all known ports if their recipe has been changed
		if not self.quiet:
			print 'Checking if any package-infos need to be updated ...'
		skippedDir = self.path + '/.skipped'
		for portName in sorted(self._portVersionsByName.keys(), key=str.lower):
			higherVersionIsActive = False
			for version in reversed(self._portVersionsByName[portName]):
				portID = portName + '-' + version
				port = allPorts[portID]

				# ignore recipes that were skipped last time unless they've
				# been changed since then
				if (os.path.exists(skippedDir + '/' + portID)
					and (os.path.getmtime(port.recipeFilePath)
						 <= os.path.getmtime(skippedDir + '/' + portID))):
					continue

				# update all package-infos of port if the recipe is newer than
				# the main package-info of that port
				mainPackageInfoFile = (self.path + '/' + port.packageInfoName)
				if (os.path.exists(mainPackageInfoFile)
					and not higherVersionIsActive
					and (os.path.getmtime(port.recipeFilePath)
						 <= os.path.getmtime(mainPackageInfoFile))):
					higherVersionIsActive = True
					break

				# try tp parse updated recipe
				try:
					port.parseRecipeFile(False)

					if higherVersionIsActive:
						# remove package infos from lower version, if it exists
						if os.path.exists(mainPackageInfoFile):
							if not self.quiet:
								print('\tremoving package-infos for ' + portID
									  + ', as newer version is active')
							port.removePackageInfosFromRepository(self.path)
							port.obsoletePackages(self.packagesPath)
							break
						continue

					status = port.getStatusOnTargetArchitecture()
					if (status != Status.STABLE
						and not (status == Status.UNTESTED
							and Configuration.shallAllowUntested())):
						touchFile(skippedDir + '/' + portID)
						if not self.quiet:
							print(('\t%s is still marked as %s on target '
								   + 'architecture') % (portID, status))
						continue

					higherVersionIsActive = True
					if os.path.exists(skippedDir + '/' + portID):
						os.remove(skippedDir + '/' + portID)

					if not self.quiet:
						print '\tupdating package infos of ' + portID
					port.writePackageInfosIntoRepository(self.path)

				except SystemExit:
					if not higherVersionIsActive:
						# take notice of broken recipe file
						touchFile(skippedDir + '/' + portID)
						if os.path.exists(mainPackageInfoFile):
							brokenPorts.append(portID)
						else:
							if not self.quiet:
								print '\trecipe for %s is still broken' % portID

		self._removeStalePackageInfos(brokenPorts)

	def _removeStalePackageInfos(self, brokenPorts):
		"""check for any package-infos that no longer have a corresponding
		   recipe file"""

		allPorts = self.getAllPorts()

		if not self.quiet:
			print "Looking for stale package-infos ..."
		packageInfos = glob.glob(self.path + '/*.PackageInfo')
		for packageInfo in packageInfos:
			packageInfoFileName = os.path.basename(packageInfo)
			packageID = packageInfoFileName[:packageInfoFileName.rindex('.')]
			portID = packageID

			# what we have in portID may be a packageID instead, in which case
			# we need to find the corresponding portID.
			if portID not in allPorts:
				portID = self.getPortIdForPackageId(portID)

			if not portID or portID not in allPorts or portID in brokenPorts:
				if not self.quiet:
					print '\tremoving ' + packageInfoFileName
				os.remove(packageInfo)

				# obsolete corresponding package, if any
				self._removePackagesForPackageInfo(packageInfo)

	def _removePackagesForPackageInfo(self, packageInfo):
		"""remove all packages for the given package-info"""

		(packageSpec, unused) = os.path.basename(packageInfo).rsplit('.', 1)
		packages = glob.glob(self.packagesPath + '/' + packageSpec + '-*.hpkg')
		obsoleteDir = self.packagesPath + '/.obsolete'
		for package in packages:
			packageFileName = os.path.basename(package)
			if not self.quiet:
				print '\tobsoleting package ' + packageFileName
			obsoletePackage = obsoleteDir + '/' + packageFileName
			if not os.path.exists(obsoleteDir):
				os.mkdir(obsoleteDir)
			os.rename(package, obsoletePackage)
