from qtpy import QtCore as QC
from qtpy import QtWidgets as QW

from hydrus.client import ClientConstants as CC
from hydrus.client import ClientGlobals as CG
from hydrus.client.gui import ClientGUIDialogsMessage
from hydrus.client.gui import QtPorting as QP
from hydrus.client.gui.panels import ClientGUIScrolledPanels
from hydrus.client.gui.search import ClientGUIACDropdown
from hydrus.client.gui.widgets import ClientGUICommon

from hydrus.client.graph import ClientGraphMigrate
from hydrus.client.graph import ClientGraphProjections
from hydrus.client.graph import ClientGraphSuggestions

# Read-only browser over the tag graph: siblings/parents/co-occurrence for a seed tag,
# double-click any result to recentre on it. Multi-hop browsing is just repeated single-hop
# recentring with a back button -- no node-link canvas, no precedent for one in this codebase
# and Hydrus has no built-in graph-drawing widget, so that would be substantial new machinery
# for what a few list views already cover.
#
# ponytail: no service selector. Edges are service-scoped, so a real explorer eventually wants
# one, but CC.DEFAULT_LOCAL_TAG_SERVICE_KEY always exists and v1 doesn't need to pick between
# multiple populated services yet. Add a dropdown when that's actually a complaint.

class TagGraphExplorerPanel( ClientGUIScrolledPanels.ReviewPanel ):
    
    def __init__( self, parent ):
        
        super().__init__( parent )
        
        self._service_key = CC.DEFAULT_LOCAL_TAG_SERVICE_KEY
        self._history = []
        
        self._seed_input = ClientGUIACDropdown.AutoCompleteDropdownTagsWrite( self, self._OnSeedChosen, CG.client_controller.new_options.GetDefaultLocalLocationContext(), self._service_key, show_paste_button = False )
        
        self._back_button = QW.QPushButton( 'back', self )
        self._back_button.clicked.connect( self._OnBack )
        self._back_button.setEnabled( False )
        
        self._rebuild_button = QW.QPushButton( 'rebuild tag graph', self )
        self._rebuild_button.setToolTip( 'Re-import siblings/parents and recompute tag co-occurrence for this service from the current data.' )
        self._rebuild_button.clicked.connect( self._OnRebuild )
        
        self._current_tag_label = ClientGUICommon.BetterStaticText( self, 'pick a tag above to start exploring' )
        
        self._siblings_list = QW.QListWidget( self )
        self._siblings_list.itemDoubleClicked.connect( self._OnListItemActivated )
        
        self._ancestors_list = QW.QListWidget( self )
        self._ancestors_list.itemDoubleClicked.connect( self._OnListItemActivated )
        
        self._related_list = QW.QListWidget( self )
        self._related_list.itemDoubleClicked.connect( self._OnListItemActivated )
        
        self._interactive_widgets = [ self._seed_input, self._back_button, self._rebuild_button, self._siblings_list, self._ancestors_list, self._related_list ]
        
        top_hbox = QP.HBoxLayout()
        
        QP.AddToLayout( top_hbox, self._back_button, CC.FLAGS_CENTER_PERPENDICULAR )
        QP.AddToLayout( top_hbox, self._seed_input, CC.FLAGS_EXPAND_BOTH_WAYS )
        QP.AddToLayout( top_hbox, self._rebuild_button, CC.FLAGS_CENTER_PERPENDICULAR )
        
        lists_hbox = QP.HBoxLayout()
        
        QP.AddToLayout( lists_hbox, self._MakeLabelledList( 'siblings (-> this ideal)', self._siblings_list ), CC.FLAGS_EXPAND_BOTH_WAYS )
        QP.AddToLayout( lists_hbox, self._MakeLabelledList( 'ancestors', self._ancestors_list ), CC.FLAGS_EXPAND_BOTH_WAYS )
        QP.AddToLayout( lists_hbox, self._MakeLabelledList( 'related (co-occurring)', self._related_list ), CC.FLAGS_EXPAND_BOTH_WAYS )
        
        vbox = QP.VBoxLayout()
        
        QP.AddToLayout( vbox, top_hbox, CC.FLAGS_EXPAND_SIZER_PERPENDICULAR )
        QP.AddToLayout( vbox, self._current_tag_label, CC.FLAGS_EXPAND_SIZER_PERPENDICULAR )
        QP.AddToLayout( vbox, lists_hbox, CC.FLAGS_EXPAND_BOTH_WAYS )
        
        self.widget().setLayout( vbox )
    
    
    def _MakeLabelledList( self, label_text, list_widget ):
        
        panel = QW.QWidget( self )
        
        vbox = QP.VBoxLayout()
        
        QP.AddToLayout( vbox, ClientGUICommon.BetterStaticText( panel, label_text ), CC.FLAGS_EXPAND_SIZER_PERPENDICULAR )
        QP.AddToLayout( vbox, list_widget, CC.FLAGS_EXPAND_BOTH_WAYS )
        
        panel.setLayout( vbox )
        
        return panel
    
    
    def _GetGraphDB( self ):
        
        graph_controller = CG.client_controller.graph_controller
        
        if graph_controller is None:
            
            ClientGUIDialogsMessage.ShowWarning( self, 'The tag graph is not enabled! Turn on the "enable_tag_graph" option and restart the client.' )
            
            return None
        
        
        return graph_controller.graph_db
    
    
    def _OnSeedChosen( self, tags ):
        
        if len( tags ) == 0:
            
            return
        
        
        self._Centre( next( iter( tags ) ), push_history = True )
    
    
    def _OnListItemActivated( self, item ):
        
        tag = item.data( QC.Qt.ItemDataRole.UserRole )
        
        self._Centre( tag, push_history = True )
    
    
    def _OnBack( self ):
        
        if len( self._history ) > 1:
            
            self._history.pop() # current tag
            
            self._Centre( self._history.pop(), push_history = True )
    
    
    
    def _Centre( self, tag, push_history ):
        
        graph_db = self._GetGraphDB()
        
        if graph_db is None:
            
            return
        
        
        ideal = graph_db.GetIdeal( tag, self._service_key )
        ancestors = sorted( graph_db.GetAncestors( ideal, self._service_key ) )
        related = ClientGraphSuggestions.GetRelatedTags( graph_db, tag, self._service_key, limit = 25 )
        
        sibling_result = graph_db.Execute(
            'MATCH (a:Tag)-[:SIBLING_OF {service_key: $service_key}]->(b:Tag {tag: $tag}) RETURN a.tag',
            { 'tag' : ideal, 'service_key' : self._service_key.hex() }
        )
        
        siblings = []
        
        while sibling_result.has_next():
            
            siblings.append( sibling_result.get_next()[ 0 ] )
        
        
        label = tag if ideal == tag else f'{tag}  (displays as: {ideal})'
        
        self._current_tag_label.setText( label )
        
        self._FillList( self._siblings_list, sorted( siblings ) )
        self._FillList( self._ancestors_list, ancestors )
        self._FillList( self._related_list, [ f'{related_tag}   (count {count}, weight {weight:.2f})' for ( related_tag, count, weight ) in related ], [ related_tag for ( related_tag, count, weight ) in related ] )
        
        if push_history:
            
            self._history.append( tag )
        
        
        self._back_button.setEnabled( len( self._history ) > 1 )
    
    
    def _FillList( self, list_widget, display_strings, underlying_tags = None ):
        
        list_widget.clear()
        
        if underlying_tags is None:
            
            underlying_tags = display_strings
        
        
        for ( display_string, tag ) in zip( display_strings, underlying_tags ):
            
            item = QW.QListWidgetItem( display_string )
            
            item.setData( QC.Qt.ItemDataRole.UserRole, tag )
            
            list_widget.addItem( item )
    
    
    
    def _OnRebuild( self ):
        
        graph_controller = CG.client_controller.graph_controller
        
        if graph_controller is None:
            
            ClientGUIDialogsMessage.ShowWarning( self, 'The tag graph is not enabled! Turn on the "enable_tag_graph" option and restart the client.' )
            
            return
        
        
        for widget in self._interactive_widgets:
            
            widget.setEnabled( False )
        
        
        self._rebuild_button.setText( 'rebuilding…' )
        
        controller = CG.client_controller
        service_key = self._service_key
        
        def work_callable():
            
            controller.db.ForceACommit()
            
            ClientGraphMigrate.ImportFromHydrusDB( graph_controller.graph_db, controller )
            ClientGraphProjections.RebuildCoOccurrence( graph_controller.graph_db, controller.db_dir, service_key )
        
        
        def publish_callable():
            
            for widget in self._interactive_widgets:
                
                widget.setEnabled( True )
            
            
            self._rebuild_button.setText( 'rebuild tag graph' )
            
            if len( self._history ) > 0:
                
                self._Centre( self._history[ -1 ], push_history = False )
        
        
        
        def do_work():
            
            work_callable()
            
            CG.client_controller.CallAfterQtSafe( self, publish_callable )
        
        
        CG.client_controller.CallToThread( do_work )
