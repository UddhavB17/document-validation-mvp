"use client";

import React, { useState } from "react";

interface RelationshipNode {
  id: string;
  name: string;
  role: "primary" | "co_applicant" | "guarantor" | "family_member";
  relation_to_primary: string | null;
  status: "match" | "mismatch" | "attention" | "n/a";
}

interface RelationshipGraphProps {
  relationships?: RelationshipNode[] | null;
}

const statusColors = {
  match: "var(--match)",
  mismatch: "var(--mismatch)",
  attention: "var(--attention)",
  "n/a": "transparent",
};

const stampText = {
  match: "Match",
  mismatch: "Mismatch",
  attention: "Review",
  "n/a": "",
};

export default function RelationshipGraph({ relationships }: RelationshipGraphProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  if (!relationships || relationships.length === 0) {
    return (
      <div className="rel-empty py-8 text-center text-[#5C6B7A] border border-dashed border-[#E1E5EB] rounded-xl text-[13px] bg-white">
        No relationship data extracted for this application.
      </div>
    );
  }

  // Dynamically assign IDs to nodes if they are missing (e.g. from old database caches)
  const nodes = relationships.map((n, index) => ({
    ...n,
    id: n.id || `${n.role}_${index}`
  }));

  // 1. Identify primary node
  let primaryNode = nodes.find((n) => n.role === "primary");
  if (!primaryNode) {
    primaryNode = nodes[0];
  }

  // 2. Separate others into co-applicants / guarantors (right side) and family members (left side)
  const others = nodes.filter((n) => n.id !== primaryNode?.id);
  const coApplicants = others.filter((n) => n.role === "co_applicant" || n.role === "guarantor");
  const familyMembers = others.filter((n) => n.role === "family_member");

  // 3. Grid Coordinates Math (viewBox="0 0 760 260")
  const cx = 380, cy = 130;
  const positions: Record<string, { x: number; y: number }> = {};

  // Primary sits at exact center
  positions[primaryNode.id] = { x: cx, y: cy };

  // Co-applicants on the right (x = 590)
  coApplicants.forEach((n, i) => {
    const total = coApplicants.length;
    const y = total > 1 ? 45 + (i * 170) / (total - 1) : cy;
    positions[n.id] = { x: 590, y };
  });

  // Family members on the left (x = 170)
  familyMembers.forEach((n, i) => {
    const total = familyMembers.length;
    const y = total > 1 ? 45 + (i * 170) / (total - 1) : cy;
    positions[n.id] = { x: 170, y };
  });

  // 4. Helper functions to render nodes and lines
  const edges = others.map((n) => {
    const p1 = positions[primaryNode.id];
    const p2 = positions[n.id];
    if (!p1 || !p2) return null;
    const midX = (p1.x + p2.x) / 2;
    const midY = (p1.y + p2.y) / 2;
    const relationLabel = n.relation_to_primary || n.role.replace("_", " ");
    
    const isHovered = hoveredNodeId === n.id;

    return (
      <g key={`edge-${n.id}`}>
        {/* Animated pulsing connector */}
        <line
          x1={p1.x}
          y1={p1.y}
          x2={p2.x}
          y2={p2.y}
          stroke={isHovered ? "var(--ledger)" : "#C7CDD6"}
          strokeWidth={isHovered ? "2" : "1.2"}
          className="flowing-connector-dashed"
          style={{
            strokeDasharray: "6, 4",
            transition: "stroke 0.2s ease, stroke-width 0.2s ease",
          }}
        />
        
        {/* Rounded background label capsule */}
        <g transform={`translate(${midX}, ${midY})`}>
          <rect
            x="-36"
            y="-9"
            width="72"
            height="18"
            rx="9"
            fill="white"
            stroke={isHovered ? "var(--ledger)" : "#E1E5EB"}
            strokeWidth="1"
            className="shadow-3xs"
            style={{ transition: "stroke 0.2s ease" }}
          />
          <text
            y="3"
            fontFamily="IBM Plex Mono"
            fontSize="9"
            fontWeight="700"
            fill={isHovered ? "var(--ledger)" : "var(--ink-soft)"}
            textAnchor="middle"
            className="uppercase tracking-wider select-none"
            style={{ transition: "fill 0.2s ease" }}
          >
            {relationLabel}
          </text>
        </g>
      </g>
    );
  });

  const nodeCards = nodes.map((n) => {
    const p = positions[n.id];
    if (!p) return null;
    const w = 168;
    const h = 58;
    const isPrimary = n.role === "primary";
    const isHovered = hoveredNodeId === n.id;

    // Mini stamp badge configurations
    const hasStatus = n.status && n.status !== "n/a";
    const stampClass = n.status === "match" ? "match" : (n.status === "mismatch" ? "mismatch" : "attention");

    let roleLabel = n.role === "primary" ? "Primary Applicant" : n.role.replace("_", " ");
    if (n.relation_to_primary) {
      roleLabel = n.relation_to_primary.charAt(0).toUpperCase() + n.relation_to_primary.slice(1);
    }

    return (
      <g
        key={`node-${n.id}`}
        transform={`translate(${p.x - w / 2}, ${p.y - h / 2})`}
        onMouseEnter={() => setHoveredNodeId(n.id)}
        onMouseLeave={() => setHoveredNodeId(null)}
        style={{ cursor: "default" }}
      >
        {/* Node box shadow/glowing filter on hover */}
        <rect
          width={w}
          height={h}
          rx="10"
          fill="var(--surface)"
          stroke={isPrimary ? "var(--ledger)" : (isHovered ? "#2B4C7E" : "#E1E5EB")}
          strokeWidth={isPrimary ? 2 : (isHovered ? 1.5 : 1.2)}
          filter={isHovered ? "drop-shadow(0 4px 8px rgba(43,76,126,0.12))" : "drop-shadow(0 2px 4px rgba(0,0,0,0.03))"}
          style={{
            transform: isHovered ? "scale(1.025)" : "scale(1)",
            transformOrigin: "center",
            transition: "transform 0.2s ease, stroke 0.2s ease, filter 0.2s ease",
          }}
        />

        {/* Avatar background */}
        <rect
          x="10"
          y="11"
          width="36"
          height="36"
          rx="8"
          fill={isPrimary ? "var(--ledger-soft)" : "#F6F7FA"}
        />

        {/* Avatar vector icons */}
        {isPrimary ? (
          <path
            d="M20 23v-1.5c0-1.6 1.4-3 3-3h4c1.6 0 3 1.4 3 3V23M28 15a3 3 0 11-6 0 3 3 0 016 0z"
            fill="none"
            stroke="var(--ledger)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            transform="translate(2, 2)"
          />
        ) : (
          <path
            d="M20 23v-1.5c0-1.6 1.4-3 3-3h4c1.6 0 3 1.4 3 3V23M28 15a3 3 0 11-6 0 3 3 0 016 0z"
            fill="none"
            stroke="var(--ink-soft)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            transform="translate(2, 2)"
          />
        )}

        {/* Name */}
        <text
          x="54"
          y="23"
          fontFamily="Inter"
          fontWeight="600"
          fontSize="11.5"
          fill="var(--ink)"
        >
          {n.name}
        </text>

        {/* Sub-label role */}
        <text
          x="54"
          y="37"
          fontFamily="Inter"
          fontSize="10"
          fill="var(--ink-soft)"
        >
          {roleLabel}
        </text>

        {/* Monospace rotated stamp status tag directly on node card */}
        {hasStatus && (
          <g transform={`translate(${w - 48}, ${h - 18}) rotate(-1.5)`}>
            <rect
              width="42"
              height="13"
              rx="1.5"
              fill={`var(--${stampClass}-soft)`}
              stroke={`var(--${stampClass})`}
              strokeWidth="0.8"
            />
            <text
              x="21"
              y="9"
              fontFamily="IBM Plex Mono"
              fontSize="7.5"
              fontWeight="700"
              fill={`var(--${stampClass})`}
              textAnchor="middle"
              className="uppercase tracking-wide"
            >
              {stampText[n.status]}
            </text>
          </g>
        )}
      </g>
    );
  });

  return (
    <div className="graph-wrap select-none bg-white p-1">
      {/* Dynamic flow offset keyframe stylesheet */}
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes pulseFlowDashed {
          from { stroke-dashoffset: 20; }
          to { stroke-dashoffset: 0; }
        }
        .flowing-connector-dashed {
          animation: pulseFlowDashed 1.2s linear infinite;
        }
      `}} />

      <svg id="relGraph" width="100%" height="260" viewBox="0 0 760 260" className="mx-auto block">
        {edges}
        {nodeCards}
      </svg>
    </div>
  );
}
