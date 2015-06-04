# TODO: refactor

# -*- coding: utf-8 -*-
from __future__ import print_function

"""GUI creator."""

#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import phy
from ..gui.qt import _prompt
from ..gui.base import BaseGUI
from .view_models import (WaveformViewModel,
                          FeatureViewModel,
                          CorrelogramViewModel,
                          TraceViewModel,
                          )


#------------------------------------------------------------------------------
# Manual clustering window
#------------------------------------------------------------------------------

def _check_list_argument(arg, name='clusters'):
    if not isinstance(arg, (list, tuple, np.ndarray)):
        raise ValueError("The argument should be a list or an array.")
    if len(name) == 0:
        raise ValueError("No {0} were selected.".format(name))


def _to_wizard_group(group_id):
    """Return the group name required by the wizard, as a function
    of the Kwik cluster group."""
    if hasattr(group_id, '__len__'):
        group_id = group_id[0]
    return {
        0: 'ignored',
        1: 'ignored',
        2: 'good',
        3: None,
        None: None,
    }.get(group_id, 'good')


def _process_ups(ups):
    """This function processes the UpdateInfo instances of the two
    undo stacks (clustering and cluster metadata) and concatenates them
    into a single UpdateInfo instance."""
    if len(ups) == 0:
        return
    elif len(ups) == 1:
        return ups[0]
    elif len(ups) == 2:
        up = ups[0]
        up.update(ups[1])
        return up
    else:
        raise NotImplementedError()


class ClusterManualGUI(BaseGUI):
    """Manual clustering GUI.

    This object represents a main window with:

    * multiple views
    * high-level clustering methods
    * global keyboard shortcuts

    Events
    ------

    cluster
    select

    """

    _vm_classes = {
        'waveforms': WaveformViewModel,
        'features': FeatureViewModel,
        'correlograms': CorrelogramViewModel,
        'traces': TraceViewModel,
    }

    def __init__(self, model=None, store=None,
                 config=None, shortcuts=None):
        self.store = store
        super(ClusterManualGUI, self).__init__(model=model,
                                               vm_classes=self._vm_classes,
                                               config=config,
                                               shortcuts=shortcuts,
                                               )

        self.connect(self._connect_view, event='add_view')
        self.start()

    # View methods
    # ---------------------------------------------------------------------

    @property
    def title(self):
        """Title of the main window."""
        name = self.__class__.__name__
        filename = self._model.kwik_path
        clustering = self._model.clustering
        channel_group = self._model.channel_group
        template = ("{filename} (shank {channel_group}, "
                    "{clustering} clustering) "
                    "- {name} - phy {version}")
        return template.format(name=name,
                               version=phy.__version__,
                               filename=filename,
                               channel_group=channel_group,
                               clustering=clustering,
                               )

    def _connect_view(self, view):
        """Connect a view to the GUI's events (select and cluster)."""
        @self.connect
        def on_select(cluster_ids):
            view.select(cluster_ids)

        @self.connect
        def on_cluster(up):
            view.on_cluster(up)

    def _create_actions(self):
        for action in ['reset_gui',
                       'save',
                       'undo',
                       'redo',
                       'show_shortcuts',
                       'exit',
                       'select',
                       'reset_wizard',
                       'first',
                       'last',
                       'next',
                       'previous',
                       'pin',
                       'unpin',
                       'merge',
                       'split',
                       ]:
            self._add_gui_shortcut(action)

        # Update the wizard selection after a clustering action.
        @self.session.connect
        def on_cluster(up):
            # Special case: split.
            if not up.history and up.description == 'assign':
                self.select(up.added)
            else:
                self._wizard_select()

        # Move best/match/both to noise/mua/good.
        def _get_clusters(which):
            return {
                'best': [self.wizard.best],
                'match': [self.wizard.match],
                'both': [self.wizard.best, self.wizard.match],
            }[which]

        def _make_func(which, group):
            """Return a function that moves best/match/both clusters to
            a group."""

            def func():
                clusters = _get_clusters(which)
                if None in clusters:
                    return
                self.session.move(clusters, group)

            name = 'move_{}_to_{}'.format(which, group)
            func.__name__ = name
            setattr(self, name, func)
            return name

        for which in ('best', 'match', 'both'):
            for group in ('noise', 'mua', 'good'):
                self._add_gui_shortcut(_make_func(which, group))

    def _set_default_view_connections(self):
        """Set view connections."""

        # Select feature dimension from waveform view.
        @self._dock.connect_views('waveforms', 'features')
        def channel_click(waveforms, features):

            @waveforms.connect
            def on_channel_click(e):
                if e.key in map(str, range(10)):
                    channel = e.channel_idx
                    dimension = int(e.key.name)
                    feature = 0 if e.button == 1 else 1
                    if (0 <= dimension <= len(features.dimensions) - 1):
                        features.dimensions[dimension] = (channel, feature)
                        # Force view update.
                        features.dimensions = features.dimensions

    # Creation methods
    # ---------------------------------------------------------------------

    def _create_cluster_metadata(self):
        self._cluster_metadata_updater = ClusterMetadataUpdater(
            self.model.cluster_metadata)

    def _create_clustering(self):
        self.clustering = Clustering(self.model.spike_clusters)

    def _create_global_history(self):
        self._global_history = GlobalHistory(process_ups=_process_ups)

    def _create_wizard(self):

        # Initialize the groups for the wizard.
        def _group(cluster):
            group_id = self._cluster_metadata_updater.group(cluster)
            return _to_wizard_group(group_id)

        groups = {cluster: _group(cluster)
                  for cluster in self.clustering.cluster_ids}
        self.wizard = Wizard(groups)

        # Set the similarity and quality functions for the wizard.
        @self.wizard.set_similarity_function
        def similarity(target, candidate):
            """Compute the dot product between the mean masks of
            two clusters."""
            return np.dot(self.store.mean_masks(target),
                          self.store.mean_masks(candidate))

        @self.wizard.set_quality_function
        def quality(cluster):
            """Return the maximum mean_masks across all channels
            for a given cluster."""
            return self.store.mean_masks(cluster).max()

        @self.connect
        def on_cluster(up):
            # HACK: get the current group as it is not available in `up`
            # currently.
            if up.description.startswith('metadata'):
                up = up.copy()
                cluster = up.metadata_changed[0]
                group = self.model.cluster_metadata.group(cluster)
                up.metadata_value = _to_wizard_group(group)
            # This called for both regular and history actions.
            # Save the wizard selection and update the wizard.
            self.wizard.on_cluster(up)

    # Open data
    # -------------------------------------------------------------------------

    def on_open(self):
        """Update the session after new data has been loaded."""
        self._create_global_history()
        self._create_clustering()
        self._create_cluster_metadata()
        self._create_cluster_store()
        self._create_wizard()

    def change_channel_group(self, channel_group):
        """Change the current channel group."""
        self.model.channel_group = channel_group
        self.emit('open')

    def change_clustering(self, clustering):
        """Change the current clustering."""
        self.model.clustering = clustering
        self.emit('open')

    # General actions
    # ---------------------------------------------------------------------

    def start(self):
        """Start the wizard."""
        self.wizard.start()
        self._cluster_ids = self.wizard.selection

    def show_shortcuts(self):
        """Show the list off all keyboard shortcuts."""
        shortcuts = self.session.settings['keyboard_shortcuts']
        _show_shortcuts(shortcuts, name=self.__class__.__name__)

    @property
    def cluster_ids(self):
        """Array of all cluster ids used in the current clustering."""
        return self.clustering.cluster_ids

    @property
    def n_clusters(self):
        """Number of clusters in the current clustering."""
        return self.clustering.n_clusters

    def register_statistic(self, func=None, shape=(-1,)):
        """Decorator registering a custom cluster statistic.

        Parameters
        ----------

        func : function
            A function that takes a cluster index as argument, and returns
            some statistics (generally a NumPy array).

        Notes
        -----

        This function will be called on every cluster when a dataset is opened.
        It is also automatically called on new clusters when clusters change.
        You can access the data from the model and from the cluster store.

        """
        if func is not None:
            return self.register_statistic()(func)

        def decorator(func):

            name = func.__name__

            def _wrapper(cluster):
                out = func(cluster)
                self.store.memory_store.store(cluster, **{name: out})

            # Add the statistics.
            stats = self.store.items['statistics']
            stats.add(name, _wrapper, shape)
            # Register it in the global cluster store.
            self.store.register_field(name, 'statistics')
            # Compute it on all existing clusters.
            stats.store_all(name=name, mode='force')
            info("Registered statistic `{}`.".format(name))

        return decorator

    def close(self):
        """Close the GUI."""
        if (self.session.settings['prompt_save_on_exit'] and
                self.session.has_unsaved_changes):
            res = _prompt(self._dock,
                          "Do you want to save your changes?",
                          ('save', 'cancel', 'close'))
            if res == 'save':
                self.save()
            elif res == 'cancel':
                return
            elif res == 'close':
                pass
        self._dock.close()

    def exit(self):
        """Close the GUI."""
        self.close()

    # Selection
    # ---------------------------------------------------------------------

    def select(self, cluster_ids):
        """Select clusters."""
        cluster_ids = list(cluster_ids)
        assert len(cluster_ids) == len(set(cluster_ids))
        # Do not re-select an already-selected list of clusters.
        if cluster_ids == self._cluster_ids:
            return
        assert set(cluster_ids) <= set(self.session.clustering.cluster_ids)
        debug("Select clusters {0:s}.".format(str(cluster_ids)))
        self._cluster_ids = cluster_ids
        self.emit('select', cluster_ids)

    @property
    def selected_clusters(self):
        """The list of selected clusters."""
        return self._cluster_ids

    # Wizard list
    # ---------------------------------------------------------------------

    def _wizard_select(self):
        self.select(self.wizard.selection)

    def reset_wizard(self):
        """Restart the wizard."""
        self.wizard.start()
        self._wizard_select()

    def first(self):
        """Go to the first cluster proposed by the wizard."""
        self.wizard.first()
        self._wizard_select()

    def last(self):
        """Go to the last cluster proposed by the wizard."""
        self.wizard.last()
        self._wizard_select()

    def next(self):
        """Go to the next cluster proposed by the wizard."""
        self.wizard.next()
        self._wizard_select()

    def previous(self):
        """Go to the previous cluster proposed by the wizard."""
        self.wizard.previous()
        self._wizard_select()

    def pin(self):
        """Pin the current best cluster."""
        self.wizard.pin()
        self._wizard_select()

    def unpin(self):
        """Unpin the current best cluster."""
        self.wizard.unpin()
        self._wizard_select()

    # Cluster actions
    # ---------------------------------------------------------------------

    def merge(self, clusters=None):
        """Merge some clusters."""
        if clusters is None:
            clusters = self.cluster_ids
        clusters = list(clusters)
        if len(clusters) <= 1:
            return
        up = self.clustering.merge(clusters)
        info("Merge clusters {} to {}.".format(str(clusters),
                                               str(up.added[0])))
        self._global_history.action(self.clustering)
        self.emit('cluster', up=up)
        return up

    def split(self, spikes=None):
        """Make a new cluster out of some spikes.

        Notes
        -----

        Spikes belonging to affected clusters, but not part of the `spikes`
        array, will move to brand new cluster ids. This is because a new
        cluster id must be used as soon as a cluster changes.

        """
        if spikes is not None:
            _check_list_argument(spikes, 'spikes')
            info("Split {0:d} spikes.".format(len(spikes)))
            up = self.clustering.split(spikes)
            self._global_history.action(self.clustering)
            self.emit('cluster', up=up)
            return up
        else:
            for features in self.get_views('features'):
                spikes = features.spikes_in_lasso()
                if spikes is not None:
                    self.split(spikes)
                    features.lasso.clear()
                    return

    def move(self, clusters, group):
        """Move some clusters to a cluster group.

        Here is the list of cluster groups:

        * 0=Noise
        * 1=MUA
        * 2=Good
        * 3=Unsorted

        """
        _check_list_argument(clusters)
        info("Move clusters {0} to {1}.".format(str(clusters), group))
        group_id = cluster_group_id(group)
        up = self._cluster_metadata_updater.set_group(clusters, group_id)
        self._global_history.action(self._cluster_metadata_updater)
        # Extra UpdateInfo fields.
        # up.update(kwargs)
        self.emit('cluster', up=up)
        return up

    def _undo_redo(self, up):
        if up:
            info("{} {}.".format(up.history.title(),
                                 up.description,
                                 ))
            self.emit('cluster', up=up)

    def undo(self):
        """Undo the last clustering action."""
        up = self._global_history.undo()
        self._undo_redo(up)
        return up

    def redo(self):
        """Redo the last undone action."""
        up = self._global_history.redo()
        self._undo_redo(up)
        return up
