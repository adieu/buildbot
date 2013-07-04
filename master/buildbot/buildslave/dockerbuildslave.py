# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Portions Copyright Buildbot Team Members

from twisted.internet import defer, threads
from twisted.python import log

from buildbot.buildslave import AbstractLatentBuildSlave
from buildbot import config, interfaces

try:
    from docker import client
    _hush_pyflakes = [client]
except ImportError:
    client = None


class DockerLatentBuildSlave(AbstractLatentBuildSlave):

    instance = None

    def __init__(self, name, password,
                 docker_host,
                 image,
                 command,
                 max_builds=None, notify_on_missing=[], missing_timeout=60*20,
                 build_wait_timeout=60*10, properties={}, locks=None):

        if not client:
            config.error("The python module 'docker-py' is needed  "
                         "to use a DockerLatentBuildSlave")

        AbstractLatentBuildSlave.__init__(
            self, name, password, max_builds, notify_on_missing,
            missing_timeout, build_wait_timeout, properties, locks)
        self.docker_host = docker_host
        self.image = image
        self.command = command

    def start_instance(self, build):
        if self.instance is not None:
            raise ValueError('instance active')
        return threads.deferToThread(self._start_instance)

    def _start_instance(self):
        # Authenticate to OpenStack.
        docker_client = client.Client(self.docker_host)
        instance = docker_client.create_container(
            self.image,
            self.command,
            environment=[
                'BUILDBOT_USER=%s' % self.slavename,
                'BUILDBOT_PASSWORD=%s' % self.password,
            ]
        )
        if instance.get('Id', None):
            self.instance = instance
            docker_client.start(instance['Id'])
            return [instance['Id'], self.image]
        else:
            raise interfaces.LatentBuildSlaveFailedToSubstantiate('Failed to start container')

    def stop_instance(self, fast=False):
        if self.instance is None:
            # be gentle.  Something may just be trying to alert us that an
            # instance never attached, and it's because, somehow, we never
            # started.
            return defer.succeed(None)
        instance = self.instance
        self.instance = None
        self._stop_instance(instance, fast)

    def _stop_instance(self, instance, fast):
        docker_client = client.Client(self.docker_host)
        docker_client.stop(instance['Id'])
        docker_client.wait(instance['Id'])

    def buildFinished(self, sb):
        self.insubstantiate()
