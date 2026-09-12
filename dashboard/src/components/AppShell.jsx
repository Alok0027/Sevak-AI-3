import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

/* The frame every signed-in page sits in.
 *
 * A persistent rail rather than buttons in a page header, for a reason
 * that isn't decoration: this product has five destinations and a
 * supervisor moves between them constantly -- district numbers, then the
 * patient the numbers are about, then the ASHA responsible for her. When
 * navigation lives in each page's header it disappears the moment you
 * drill in, and you navigate by browser Back. A rail keeps the whole
 * service visible from anywhere in it, and keeps the page body for the
 * one thing that page is about.
 *
 * The rail also carries scope. "District-wide" versus "Your sub-centre"
 * is the single most important fact about every number on screen, and it
 * belongs next to who you are signed in as, because that is what decides
 * it -- not floating in a page subtitle where it reads as a caption. */

const ROLE_LABEL = {
  bmo: "Block Medical Officer",
  anm: "Auxiliary Nurse Midwife",
  admin: "Administrator",
  asha: "ASHA worker",
};

function initials(name) {
  if (!name) return "–";
  return name
    .trim()
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function AppShell({ title, scope, meta, actions, children }) {
  const { auth, logout } = useAuth();
  const navigate = useNavigate();
  const isAdmin = auth?.role === "admin";

  const signOut = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="rail-brand">
          {/* The mark is the status rail itself, stood on end: the same
              3px bar that runs down every row in the product. */}
          <span className="rail-mark" aria-hidden="true" />
          <span className="rail-wordmark">SevakAI</span>
        </div>

        <ul className="rail-nav">
          <RailLink to="/" end label="Overview" hint="Numbers and accountability" />
          <RailLink to="/patients" label="Patients" hint="Everyone under care" />
          {isAdmin && <RailLink to="/admin" label="Administration" hint="Workers and audit" />}
        </ul>

        <div className="rail-foot">
          {scope && <p className="rail-scope">{scope}</p>}
          <div className="rail-user">
            <span className="avatar" aria-hidden="true">
              {initials(auth?.workerName)}
            </span>
            <span className="rail-user-text">
              <span className="rail-user-name">{auth?.workerName || "Signed in"}</span>
              <span className="rail-user-role">{ROLE_LABEL[auth?.role] ?? auth?.role}</span>
            </span>
          </div>
          <button className="btn-quiet rail-signout" onClick={signOut}>
            Sign out
          </button>
        </div>
      </nav>

      <div className="shell-body">
        <header className="page-head">
          <div className="page-head-text">
            <h1>{title}</h1>
            {meta && <p className="page-meta">{meta}</p>}
          </div>
          {actions && <div className="page-actions">{actions}</div>}
        </header>
        <main className="page-body">{children}</main>
      </div>
    </div>
  );
}

function RailLink({ to, end, label, hint }) {
  return (
    <li>
      <NavLink to={to} end={end} className={({ isActive }) => (isActive ? "rail-link is-active" : "rail-link")}>
        {/* The active marker is the rail motif again -- a bar on the
            leading edge, not a filled pill. Consistent with how a row
            says "this one" everywhere else in the product. */}
        <span className="rail-link-bar" aria-hidden="true" />
        <span className="rail-link-text">
          <span className="rail-link-label">{label}</span>
          <span className="rail-link-hint">{hint}</span>
        </span>
      </NavLink>
    </li>
  );
}
