import { useEffect, useState } from 'react';
import ProjectsView from './pages/ProjectsView';
import EditorView from './pages/EditorView';

/** Parse the current location hash into a route. */
function parseHash(): { view: 'projects' } | { view: 'editor'; projectId: string } {
  const h = window.location.hash.replace(/^#/, '');
  const m = h.match(/^\/project\/([^/]+)/);
  if (m) return { view: 'editor', projectId: decodeURIComponent(m[1]) };
  return { view: 'projects' };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  if (route.view === 'editor') {
    // key by projectId so switching projects fully remounts the editor
    return <EditorView key={route.projectId} projectId={route.projectId} />;
  }
  return <ProjectsView />;
}
