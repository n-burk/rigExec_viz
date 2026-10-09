"""usdview host integration. The visualizer never owns an evaluator."""
import os
from pxr import Tf
from pxr.Usdviewq.plugin import PluginContainer
from pxr.Usdviewq.qt import QtCore


class LiveVizContainer(PluginContainer):
    def registerPlugins(self, registry, api):
        self.api, self.window = api, None
        self.command = registry.registerCommandPlugin('RigExecLiveViz.open', 'Live Graph and Threads', self.open)
        if os.environ.get('RIGEXEC_VIZ_AUTOOPEN') == '1':
            QtCore.QTimer.singleShot(2000, lambda: self.open(api))

    def configureView(self, registry, builder):
        builder.findOrCreateMenu('RigExec').findOrCreateSubmenu('General Editors').addItem(self.command)

    def open(self, api):
        if self.window is None or not self.window.isVisible():
            if self.window is not None:
                self.window.deleteLater()
            from .session import LiveSession
            from .window import RigVizWindow
            self.window = RigVizWindow(LiveSession(api, os.environ.get('RIGEXEC_VIZ_RIG', '')), api.qMainWindow)
        self.window.show(); self.window.raise_()


Tf.Type.Define(LiveVizContainer)
