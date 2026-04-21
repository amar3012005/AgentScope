import { useLocation } from "react-router-dom";
import { getRouteMeta } from "../router/route-metadata";

export function Topbar(): JSX.Element {
  const location = useLocation();
  const route = getRouteMeta(location.pathname);

  return (
    <header className="topbar">
      <div className="topbar__left">
        <h2 className="topbar__title">{route.title}</h2>
        <span className="topbar__badge">{route.eyebrow}</span>
      </div>
      <div className="topbar__right">
        <span className="topbar__usage">
          Usage 3 / 1,000 runs
        </span>
        <button type="button" className="topbar__upgrade">
          Upgrade
        </button>
      </div>
    </header>
  );
}
