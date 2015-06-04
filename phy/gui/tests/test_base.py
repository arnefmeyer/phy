# -*- coding: utf-8 -*-1

"""Tests of base classes."""

#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import os.path as op

from pytest import raises

from ..base import (BaseViewModel, HTMLViewModel, WidgetCreator,
                    BaseGUI, BaseSession,
                    )
from ..qt import (QtGui,
                  wrap_qt,
                  _set_qt_widget_position_size,
                  )
from ...utils.event import EventEmitter
from ...utils.logging import set_level
from ...utils.tempdir import TemporaryDirectory
from ...io.base_model import BaseModel


#------------------------------------------------------------------------------
# Base tests
#------------------------------------------------------------------------------

def setup():
    set_level('debug')


def teardown():
    set_level('info')


@wrap_qt
def test_base_view_model():
    class MyViewModel(BaseViewModel):
        _view_name = 'main_window'
        _imported_params = ('text',)

        def _create_view(self, text='', position=None, size=None):
            view = QtGui.QMainWindow()
            view.setWindowTitle(text)
            _set_qt_widget_position_size(view,
                                         position=position,
                                         size=size,
                                         )
            return view

    size = (400, 100)
    text = 'hello'

    vm = MyViewModel(text=text, size=size)
    vm.show()
    yield

    assert vm.view.windowTitle() == text
    assert vm.text == text
    assert vm.size == size
    assert (vm.view.width(), vm.view.height()) == size

    vm.close()
    yield


@wrap_qt
def test_html_view_model():
    vm = HTMLViewModel(html='hello world!')
    vm.show()
    yield
    vm.close()


def test_widget_creator():

    class MyWidget(EventEmitter):
        """Mock widget."""
        def __init__(self, param=None):
            super(MyWidget, self).__init__()
            self.name = 'my_widget'
            self._shown = False
            self.param = param

        @property
        def shown(self):
            return self._shown

        def close(self, e=None):
            self.emit('close', e)
            self._shown = False

        def show(self):
            self._shown = True

    widget_classes = {'my_widget': MyWidget}

    wc = WidgetCreator(widget_classes=widget_classes)
    assert not wc.get()
    assert not wc.get('my_widget')

    with raises(ValueError):
        wc.add('my_widget_bis')

    for show in (False, True):
        w = wc.add('my_widget', show=show, param=show)
        assert len(wc.get()) == 1
        assert len(wc.get('my_widget')) == 1

        assert w.shown is show
        assert w.param is show
        w.show()
        assert w.shown

        w.close()
        assert not wc.get()
        assert not wc.get('my_widget')


@wrap_qt
def test_base_gui():

    class V1(HTMLViewModel):
        _html = 'view 1'

    class V2(HTMLViewModel):
        _html = 'view 2'

    class V3(HTMLViewModel):
        _html = 'view 3'

    vm_classes = {'v1': V1, 'v2': V2, 'v3': V3}

    config = [('v1', {'position': 'right'}),
              ('v2', {'position': 'left'}),
              ('v2', {'position': 'bottom'}),
              ('v3', {'position': 'left'}),
              ]

    shortcuts = {'test': 't'}

    class TestGUI(BaseGUI):
        def __init__(self):
            super(TestGUI, self).__init__(vm_classes=vm_classes,
                                          config=config,
                                          shortcuts=shortcuts,
                                          )

        def _create_actions(self):
            self._add_gui_shortcut('test')

        def test(self):
            self.show_shortcuts()
            self.reset_gui()

    gui = TestGUI()
    gui.show()
    yield

    v2 = gui.get_views('v2')
    assert len(v2) == 2
    v2[1].close()
    yield

    v3 = gui.get_views('v3')
    v3[0].close()
    yield

    gui.reset_gui()
    yield

    gui.close()
    yield


def test_base_session():

    model = BaseModel()

    class V1(HTMLViewModel):
        _html = 'view 1'

    class V2(HTMLViewModel):
        _html = 'view 2'

    vm_classes = {'v1': V1, 'v2': V2}

    config = [('v1', {'position': 'right'}),
              ('v2', {'position': 'left'}),
              ('v2', {'position': 'bottom'}),
              ]

    shortcuts = {'test': 't', 'close': 'ctrl+q'}

    class TestGUI(BaseGUI):
        def __init__(self, **kwargs):
            super(TestGUI, self).__init__(vm_classes=vm_classes,
                                          **kwargs)

        def _create_actions(self):
            self._add_gui_shortcut('test')
            self._add_gui_shortcut('close')

        def test(self):
            self.show_shortcuts()
            self.reset_gui()

    gui_classes = {'gui': TestGUI}

    with TemporaryDirectory() as tmpdir:

        default_settings_path = op.join(tmpdir, 'default_settings.py')

        with open(default_settings_path, 'w') as f:
            f.write("gui_config = {}\n".format(str(config)) +
                    "gui_shortcuts = {}".format(str(shortcuts)))

        session = BaseSession(model=model,
                              phy_user_dir=tmpdir,
                              default_settings_path=default_settings_path,
                              vm_classes=vm_classes,
                              gui_classes=gui_classes,
                              )

        # Need to wrap here because of the temporary directory.
        @wrap_qt
        def test():
            view = session.show_view('v1')
            yield view
            view.close()

            # New GUI.
            gui = session.show_gui('gui')
            yield gui

            # Remove a v2 view.
            v2 = gui.get_views('v2')
            assert len(v2) == 2
            v2[0].close()
            yield
            gui.close()

            # Reopen and check that the v2 is gone.
            gui = session.show_gui('gui')
            v2 = gui.get_views('v2')
            assert len(v2) == 1
            yield gui
            # gui.close()

            gui.reset_gui()
            v2 = gui.get_views('v2')
            assert len(v2) == 2
            yield
            gui.close()

            gui = session.show_gui('gui')
            yield gui

            v2 = gui.get_views('v2')
            assert len(v2) == 2
            gui.close()
            yield gui

        test()
