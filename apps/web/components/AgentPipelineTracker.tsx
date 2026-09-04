"use client";

import { Loader2, Sparkles, Database, FileSearch, Eye, Mic } from "lucide-react";

export interface PipelineNodeEvent {
  node: string;
  detail?: string;
  timestamp?: number;
}

interface AgentPipelineTrackerProps {
  activeNode: string | null;
  history: PipelineNodeEvent[];
  streaming: boolean;
  confidence?: number | null;
  capabilities?: string[];
}

const STEP_LABELS: Record<string, { label: string; icon: React.ComponentType<{ size?: number; className?: string }> }> = {
  transcribe: { label: "Transcribing Audio", icon: Mic },
  classify: { label: "Routing Query", icon: Sparkles },
  rag: { label: "Searching Documents", icon: FileSearch },
  data: { label: "Analyzing Dataset", icon: Database },
  vision: { label: "Extracting Vision / OCR", icon: Eye },
  fuse: { label: "Synthesizing Evidence", icon: Sparkles },
  verify: { label: "Verifying Facts", icon: Sparkles },
  generate: { label: "Generating Answer", icon: Sparkles },
};

export default function AgentPipelineTracker({
  activeNode,
  history,
  streaming,
}: AgentPipelineTrackerProps) {
  // Only render during active thinking/streaming — status chip only,
  // no internal node chatter.
  if (!streaming || history.length === 0) return null;

  const currentStep = activeNode || history[history.length - 1]?.node || "classify";
  const stepInfo = STEP_LABELS[currentStep] || { label: "Investigating", icon: Sparkles };
  const Icon = stepInfo.icon;

  return (
    <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-black/[.08] bg-white/90 py-1.5 pl-2 pr-3 shadow-sm backdrop-blur-md">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
        <Loader2 size={13} className="animate-spin" />
      </span>
      <span className="flex items-center gap-1.5 text-xs font-medium text-gray-800">
        <Icon size={13} className="text-indigo-500" />
        {stepInfo.label}…
      </span>
    </div>
  );
}
