"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, FileText, Layers, ArrowRight } from "lucide-react";

/**
 * ContentDirectorLoader — Animation shown while Content Director is planning
 *
 * Displays an engaging multi-step animation showing:
 * - Evidence being processed
 * - Content structure being built
 * - Distribution plan being created
 */

const STEPS = [
  {
    id: "analyzing",
    icon: FileText,
    title: "Analyzing evidence",
    description: "Reviewing research findings and key insights",
    color: "#3b82f6",
    gradient: ["#dbeafe", "#eff6ff"],
  },
  {
    id: "structuring",
    icon: Layers,
    title: "Building structure",
    description: "Organizing content into logical sections",
    color: "#8b5cf6",
    gradient: ["#ede9fe", "#f5f3ff"],
  },
  {
    id: "planning",
    icon: Sparkles,
    title: "Planning distribution",
    description: "Mapping content to optimal renderers",
    color: "#f59e0b",
    gradient: ["#fef3c7", "#fffbeb"],
  },
];

export function ContentDirectorLoader({ isVisible = false }) {
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    if (!isVisible) {
      setCurrentStep(0);
      return;
    }

    // Cycle through steps while content director is working
    const interval = setInterval(() => {
      setCurrentStep((prev) => (prev + 1) % STEPS.length);
    }, 2500);

    return () => clearInterval(interval);
  }, [isVisible]);

  if (!isVisible) return null;

  const current = STEPS[currentStep];
  const IconComponent = current.icon;

  return (
    <div className="rounded-[24px] border border-[rgba(0,0,0,0.06)] bg-[#faf9f4] p-4 shadow-[0_12px_32px_rgba(0,0,0,0.04)]">
      {/* Header with animated sparkles */}
      <div className="flex items-center gap-2 mb-4">
        <motion.div
          animate={{
            rotate: [0, 10, -10, 0],
            scale: [1, 1.1, 1],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          <Sparkles size={18} className="text-[#f59e0b]" />
        </motion.div>
        <span className="text-xs font-medium text-[#6b7280] uppercase tracking-wider">
          Content Director
        </span>
      </div>

      {/* Progress bar */}
      <div className="relative h-1.5 w-full rounded-full bg-[#e3e0db] overflow-hidden mb-4">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[#ff5c4b] via-[#f59e0b] to-[#8b5cf6]"
          initial={{ width: "0%" }}
          animate={{ width: `${((currentStep + 1) / STEPS.length) * 100}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
        {/* Shimmer effect */}
        <motion.div
          className="absolute inset-y-0 left-0 w-full"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent)",
          }}
          animate={{ x: ["-100%", "100%"] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
        />
      </div>

      {/* Step indicators */}
      <div className="flex items-center justify-between mb-4">
        {STEPS.map((step, index) => {
          const StepIcon = step.icon;
          const isActive = index === currentStep;
          const isCompleted = index < currentStep;

          return (
            <React.Fragment key={step.id}>
              <motion.div
                className="flex flex-col items-center gap-1.5"
                animate={{
                  scale: isActive ? 1.05 : 1,
                }}
                transition={{ duration: 0.2 }}
              >
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full border-2 transition-colors ${
                    isCompleted
                      ? "bg-[#10b981] border-[#10b981]"
                      : isActive
                      ? `border-[${step.color}] bg-white`
                      : "border-[#e3e0db] bg-white"
                  }`}
                  style={isActive ? { borderColor: step.color } : {}}
                >
                  {isCompleted ? (
                    <motion.div
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ type: "spring", stiffness: 500, damping: 25 }}
                    >
                      <svg
                        className="h-4 w-4 text-white"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={3}
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    </motion.div>
                  ) : (
                    <StepIcon
                      size={14}
                      className={isCompleted ? "text-white" : "text-[#9ca3af]"}
                      style={isActive ? { color: step.color } : {}}
                    />
                  )}
                </div>
              </motion.div>

              {/* Connector line */}
              {index < STEPS.length - 1 && (
                <div className="flex-1 mx-2 mb-6">
                  <div className="h-0.5 w-full rounded-full bg-[#e3e0db] relative overflow-hidden">
                    <motion.div
                      className="absolute inset-y-0 left-0 h-full bg-gradient-to-r from-transparent via-[#ff5c4b] to-transparent"
                      initial={{ x: "-100%" }}
                      animate={{ x: "100%" }}
                      transition={{
                        duration: 1.5,
                        repeat: Infinity,
                        ease: "linear",
                        delay: index * 0.5,
                      }}
                    />
                  </div>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Animated content area */}
      <div className="rounded-[18px] bg-white border border-[#e3e0db] p-3 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={current.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            {/* Icon with pulse */}
            <motion.div
              className="flex h-10 w-10 items-center justify-center rounded-xl mb-2"
              style={{
                background: `linear-gradient(135deg, ${current.gradient[0]}, ${current.gradient[1]})`,
              }}
              animate={{
                boxShadow: [
                  `0 0 0 0 ${current.color}40`,
                  `0 0 0 8 ${current.color}00`,
                ],
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
                ease: "easeOut",
              }}
            >
              <IconComponent size={20} style={{ color: current.color }} />
            </motion.div>

            {/* Title */}
            <h3 className="text-sm font-semibold text-[#111827]">
              {current.title}
            </h3>

            {/* Description */}
            <p className="text-xs text-[#6b7280] mt-1">{current.description}</p>

            {/* Animated bars showing progress */}
            <div className="mt-3 space-y-1.5">
              {[1, 2, 3].map((i) => (
                <motion.div
                  key={i}
                  className="h-1.5 rounded-full bg-[#f3f4f6] overflow-hidden"
                  initial={{ opacity: 0.5 }}
                  animate={{ opacity: [0.5, 1, 0.5] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    delay: i * 0.15,
                    ease: "easeInOut",
                  }}
                >
                  <motion.div
                    className="h-full rounded-full"
                    style={{
                      background: `linear-gradient(90deg, ${current.color}, ${current.color}88)`,
                    }}
                    initial={{ width: "20%" }}
                    animate={{ width: ["20%", "60%", "40%"] }}
                    transition={{
                      duration: 1.5,
                      repeat: Infinity,
                      delay: i * 0.2,
                      ease: "easeInOut",
                    }}
                  />
                </motion.div>
              ))}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Status text */}
      <div className="flex items-center justify-center gap-1.5 mt-3 text-xs text-[#9ca3af]">
        <motion.div
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          className="flex items-center gap-1"
        >
          <span>Planning content flow</span>
          <ArrowRight size={12} />
          <span>Preparing artifact</span>
        </motion.div>
      </div>
    </div>
  );
}

export default ContentDirectorLoader;
