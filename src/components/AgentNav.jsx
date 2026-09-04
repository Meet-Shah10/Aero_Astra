/* Adapted from the provided CardNav — same hamburger-toggle + GSAP expand
   mechanism, but the panel opens a VERTICAL stack of agent buttons (top to
   bottom) instead of a horizontal row of link cards, to fit the sidebar. */
import { useLayoutEffect, useRef, useState } from 'react';
import { gsap } from 'gsap';
import './AgentNav.css';

const AgentNav = ({ agents, activeAgent, onSelect, ease = 'power3.out' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef(null);
  const itemsRef = useRef([]);
  const tlRef = useRef(null);

  const createTimeline = () => {
    const panelEl = panelRef.current;
    if (!panelEl) return null;

    gsap.set(panelEl, { height: 0, overflow: 'hidden' });
    gsap.set(itemsRef.current, { y: -14, opacity: 0 });

    const tl = gsap.timeline({ paused: true });
    tl.to(panelEl, { height: 'auto', duration: 0.35, ease });
    tl.to(itemsRef.current, { y: 0, opacity: 1, duration: 0.3, ease, stagger: 0.045 }, '-=0.15');
    return tl;
  };

  useLayoutEffect(() => {
    const tl = createTimeline();
    tlRef.current = tl;
    return () => {
      tl?.kill();
      tlRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents]);

  const toggle = () => {
    const tl = tlRef.current;
    if (!tl) return;
    if (!isOpen) {
      setIsOpen(true);
      tl.play(0);
    } else {
      tl.eventCallback('onReverseComplete', () => setIsOpen(false));
      tl.reverse();
    }
  };

  return (
    <div className="agent-nav">
      <button
        type="button"
        className={`agent-nav-toggle ${isOpen ? 'open' : ''}`}
        onClick={toggle}
        aria-expanded={isOpen}
        aria-label={isOpen ? 'Close agent list' : 'Open agent list'}
      >
        <span className="agent-nav-toggle-label">
          AGENT CONSOLE
          {activeAgent && <span className="agent-nav-toggle-active"> — {activeAgent}</span>}
        </span>
        <span className="hamburger-lines">
          <span className="hamburger-line" />
          <span className="hamburger-line" />
        </span>
      </button>

      <div className="agent-nav-panel" ref={panelRef}>
        {agents.map((agent, i) => (
          <button
            type="button"
            key={agent.code}
            ref={el => { if (el) itemsRef.current[i] = el; }}
            className={`agent-nav-item ${activeAgent === agent.code ? 'is-active' : ''}`}
            onClick={() => onSelect(agent.code)}
          >
            <span className="agent-nav-item-code">{agent.code}</span>
            <span className="agent-nav-item-role">{agent.role}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default AgentNav;
