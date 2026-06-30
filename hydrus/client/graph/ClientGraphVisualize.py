import html
import json
import os

from hydrus import external

from hydrus.client.graph import ClientGraphSuggestions

# Builds a bounded, pre-fetched neighbourhood around a seed tag and renders it as a self-contained
# HTML file (D3 force-directed graph) opened in the user's browser via ClientPaths.LaunchPathInWebBrowser.
# No QtWebEngine dependency (not in this project's stack) and no live query server (v1) -- the
# whole 2-hop neighbourhood is dumped up front, and the page reveals nodes/edges progressively as
# the user clicks, entirely client-side. To explore past the dumped edge, re-seed from the panel.

D3_PATH = os.path.join( os.path.dirname( external.__file__ ), 'd3.v7.min.js' )

HOP_1_RELATED_LIMIT = 15
HOP_2_RELATED_LIMIT = 5
DEFAULT_MAX_NODES = 80


def BuildNeighborhood( graph_db, seed_tag, service_key, max_nodes = DEFAULT_MAX_NODES ):
    
    nodes = set()
    edges = []
    seen_edges = set()
    
    def add_edge( source, target, edge_type, directed, weight = None ):
        
        key = ( source, target, edge_type )
        
        if key in seen_edges:
            
            return
        
        
        seen_edges.add( key )
        edges.append( { 'source' : source, 'target' : target, 'type' : edge_type, 'directed' : directed, 'weight' : weight } )
    
    
    def expand( tag, related_limit ):
        
        ideal = graph_db.GetIdeal( tag, service_key )
        
        nodes.add( ideal )
        
        if ideal != tag:
            
            nodes.add( tag )
            add_edge( tag, ideal, 'SIBLING_OF', True )
        
        
        siblings = graph_db.GetSiblings( ideal, service_key )
        
        for bad_tag in siblings:
            
            nodes.add( bad_tag )
            add_edge( bad_tag, ideal, 'SIBLING_OF', True )
        
        
        ancestors = sorted( graph_db.GetAncestors( ideal, service_key ) )
        
        for ancestor_tag in ancestors:
            
            nodes.add( ancestor_tag )
            add_edge( ideal, ancestor_tag, 'PARENT_OF', True )
        
        
        related = ClientGraphSuggestions.GetRelatedTags( graph_db, tag, service_key, limit = related_limit )
        
        for ( related_tag, count, weight ) in related:
            
            nodes.add( related_tag )
            add_edge( ideal, related_tag, 'CO_OCCURS', False, weight )
        
        
        return siblings + ancestors + [ related_tag for ( related_tag, _count, _weight ) in related ]
    
    
    nodes.add( seed_tag )
    
    hop_1_neighbors = expand( seed_tag, HOP_1_RELATED_LIMIT )
    
    for neighbor_tag in hop_1_neighbors:
        
        if len( nodes ) >= max_nodes:
            
            break
        
        
        expand( neighbor_tag, HOP_2_RELATED_LIMIT )
    
    
    return { 'seed' : seed_tag, 'nodes' : sorted( nodes ), 'edges' : edges }



HTML_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf8">
<title>hydrus tag graph: __HYDRUS_SEED_TITLE__</title>
<style>
  body { margin: 0; font-family: sans-serif; background: #fafafa; }
  #hint { position: absolute; top: 8px; left: 8px; max-width: 360px; font-size: 12px; color: #555; background: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; }
  #legend { position: absolute; top: 8px; right: 8px; font-size: 12px; background: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; line-height: 1.6; }
  .legend-line { display: inline-block; width: 28px; height: 0; border-top: 2px solid; margin-right: 4px; vertical-align: middle; }
  .node circle { stroke: #fff; stroke-width: 1.5px; cursor: pointer; }
  .node text { font-size: 11px; pointer-events: none; }
  .edge.SIBLING_OF { stroke: #3b78c2; stroke-width: 1.5px; fill: none; }
  .edge.PARENT_OF { stroke: #2e8b57; stroke-width: 1.5px; fill: none; }
  .edge.CO_OCCURS { stroke: #999; stroke-width: 1px; stroke-dasharray: 4 3; fill: none; }
</style>
</head>
<body>
<div id="hint">Click a node to reveal its already-fetched neighbours. Drag to reposition, scroll to zoom. This is a bounded snapshot around <b>__HYDRUS_SEED_TITLE__</b> -- to explore further out, re-seed from the Hydrus tag graph explorer panel.</div>
<div id="legend">
  <div><span class="legend-line" style="border-color:#3b78c2"></span>sibling (bad &rarr; ideal)</div>
  <div><span class="legend-line" style="border-color:#2e8b57"></span>parent (child &rarr; ancestor)</div>
  <div><span class="legend-line" style="border-color:#999; border-top-style:dashed"></span>co-occurs</div>
</div>
<svg></svg>
<script>__HYDRUS_D3_SOURCE__</script>
<script>
const DATA = __HYDRUS_DATA_JSON__;

const svg = d3.select('svg');
const width = window.innerWidth;
const height = window.innerHeight;
svg.attr('width', width).attr('height', height);

const defs = svg.append('defs');

[['SIBLING_OF', '#3b78c2'], ['PARENT_OF', '#2e8b57']].forEach(([type, color]) => {
  defs.append('marker')
    .attr('id', 'arrow-' + type)
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', color);
});

const g = svg.append('g');
svg.call(d3.zoom().scaleExtent([0.1, 4]).on('zoom', (event) => g.attr('transform', event.transform)));

g.append('g').attr('class', 'links');
g.append('g').attr('class', 'nodes');

function edgeKey(e) { return e.source + '|' + e.target + '|' + e.type; }

const adjacency = new Map();
function addAdj(tag, edge, other) {
  if (!adjacency.has(tag)) adjacency.set(tag, []);
  adjacency.get(tag).push({edge, other});
}
DATA.edges.forEach(e => { addAdj(e.source, e, e.target); addAdj(e.target, e, e.source); });

const visibleNodeIds = new Set();
const visibleEdgeKeys = new Set();
const nodeById = new Map();

const simulation = d3.forceSimulation()
  .force('link', d3.forceLink().id(d => d.id).distance(80))
  .force('charge', d3.forceManyBody().strength(-220))
  .force('center', d3.forceCenter(width / 2, height / 2))
  .force('collide', d3.forceCollide(26));

let nodeSel = g.select('.nodes').selectAll('g.node');
let linkSel = g.select('.links').selectAll('line');

function drag(sim) {
  function started(event, d) { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
  function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
  function ended(event, d) { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }
  return d3.drag().on('start', started).on('drag', dragged).on('end', ended);
}

function revealNode(tag) {
  visibleNodeIds.add(tag);
  (adjacency.get(tag) || []).forEach(({edge, other}) => {
    visibleNodeIds.add(other);
    visibleEdgeKeys.add(edgeKey(edge));
  });
  update();
}

function update() {
  const simNodes = [...visibleNodeIds].map(id => {
    let n = nodeById.get(id);
    if (!n) { n = {id}; nodeById.set(id, n); }
    return n;
  });
  
  const simLinks = DATA.edges.filter(e => visibleEdgeKeys.has(edgeKey(e))).map(e => ({...e}));
  
  linkSel = linkSel.data(simLinks, edgeKey);
  linkSel.exit().remove();
  linkSel = linkSel.enter().append('line')
    .attr('class', d => 'edge ' + d.type)
    .attr('marker-end', d => d.directed ? `url(#arrow-${d.type})` : null)
    .attr('stroke-opacity', d => d.type === 'CO_OCCURS' ? Math.min(1, 0.3 + (d.weight || 1) / 10) : 1)
    .merge(linkSel);
  
  nodeSel = nodeSel.data(simNodes, d => d.id);
  nodeSel.exit().remove();
  const nodeEnter = nodeSel.enter().append('g').attr('class', 'node')
    .call(drag(simulation))
    .on('click', (event, d) => revealNode(d.id));
  nodeEnter.append('circle')
    .attr('r', d => d.id === DATA.seed ? 12 : 8)
    .attr('fill', d => d.id === DATA.seed ? '#e07b39' : '#4c78a8');
  nodeEnter.append('text').text(d => d.id).attr('dx', 12).attr('dy', 4);
  nodeSel = nodeEnter.merge(nodeSel);
  
  simulation.nodes(simNodes).on('tick', ticked);
  simulation.force('link').links(simLinks);
  simulation.alpha(0.8).restart();
}

function ticked() {
  linkSel.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  nodeSel.attr('transform', d => `translate(${d.x},${d.y})`);
}

revealNode(DATA.seed);
</script>
</body>
</html>
'''


def GenerateHTML( neighborhood ):
    
    with open( D3_PATH, 'r', encoding = 'utf8' ) as f:
        
        d3_source = f.read()
    
    
    # plain token replacement, not str.format() -- the template is full of literal CSS/JS braces
    # (including JS template-literal ${...} syntax), so both .format() and string.Template would
    # misparse it. data_json additionally guards against a tag containing a literal "</script>"
    # breaking out of the embedding <script> tag.
    data_json = json.dumps( neighborhood ).replace( '</', '<\\/' )
    
    html_text = HTML_TEMPLATE
    html_text = html_text.replace( '__HYDRUS_SEED_TITLE__', html.escape( neighborhood[ 'seed' ] ) )
    html_text = html_text.replace( '__HYDRUS_D3_SOURCE__', d3_source )
    html_text = html_text.replace( '__HYDRUS_DATA_JSON__', data_json )
    
    return html_text
