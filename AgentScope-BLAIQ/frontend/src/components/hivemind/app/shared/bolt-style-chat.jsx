'use client'

import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  Plus, Lightbulb, Paperclip, Image, FileCode,
  ChevronDown, Check, Sparkles, Zap, Brain, Bolt, Github,
  SendHorizontal, BarChart3, BookOpen, Search, Globe, MessageSquare, FileUp
} from 'lucide-react'
import { useBlaiqWorkspace } from './blaiq-workspace-context'
import { uploadFile } from './blaiq-client'

// MODELS CONFIG
const models = [
  { id: 'sonnet-4.5', name: 'Sonnet 4.5', description: 'Fast & intelligent', icon: Zap, iconColor: 'text-blue-400', badge: 'Default' },
  { id: 'opus-4.5', name: 'Opus 4.5', description: 'Most capable', icon: Sparkles, iconColor: 'text-purple-400', badge: 'Pro' },
  { id: 'haiku-4.5', name: 'Haiku 4.5', description: 'Lightning fast', icon: Brain, iconColor: 'text-emerald-400' },
  { id: 'gemini-2.0', name: 'Gemini 2.0', description: 'Google AI', icon: Brain, iconColor: 'text-cyan-400' },
]

// ANALYSIS MODES
const analysisModes = [
  { id: 'standard', name: 'Standard', description: 'Fast recall', icon: Zap, iconColor: 'text-amber-400' },
  { id: 'deep_research', name: 'Deep Research', description: 'Full decomposition', icon: Brain, iconColor: 'text-purple-400' },
  { id: 'finance', name: 'Finance', description: 'Hypothesis-driven', icon: BarChart3, iconColor: 'text-emerald-400' },
  { id: 'data_science', name: 'Data Science', description: 'Code execution', icon: FileCode, iconColor: 'text-blue-400' },
]

function ModelSelector({ selectedModel, onModelChange, isDayMode }) {
  const [isOpen, setIsOpen] = useState(false)
  const selected = models.find(m => m.id === selectedModel) || models[0]
  const IconComponent = selected.icon

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all duration-200 ${
          isDayMode
            ? 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
            : 'text-[#8a8a8f] hover:text-white hover:bg-white/5'
        }`}
      >
        <IconComponent className={`size-4 ${selected.iconColor}`} />
        <span>{selected.name}</span>
        <ChevronDown className={`size-3.5 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className={`absolute bottom-full left-0 mb-2 z-50 min-w-[220px] backdrop-blur-xl border rounded-xl shadow-2xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200 ${
            isDayMode
              ? 'bg-white/95 border-gray-200 shadow-gray-200/50'
              : 'bg-[#1a1a1e]/95 border-white/10 shadow-black/50'
          }`}>
            <div className="p-1.5">
              <div className={`px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider ${
                isDayMode ? 'text-gray-500' : 'text-[#5a5a5f]'
              }`}>
                Select Model
              </div>
              {models.map((model) => {
                const ModelIcon = model.icon
                return (
                  <button
                    key={model.id}
                    onClick={() => {
                      onModelChange?.(model.id)
                      setIsOpen(false)
                    }}
                    className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-left transition-all duration-150 ${
                      selected.id === model.id
                        ? isDayMode ? 'bg-gray-100 text-gray-900' : 'bg-white/10 text-white'
                        : isDayMode ? 'text-gray-600 hover:bg-gray-50 hover:text-gray-900' : 'text-[#a0a0a5] hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    <div className="flex-shrink-0"><ModelIcon className={`size-4 ${model.iconColor}`} /></div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{model.name}</span>
                        {model.badge && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            model.badge === 'Pro' ? 'bg-purple-500/20 text-purple-300' : 'bg-blue-500/20 text-blue-300'
                          }`}>
                            {model.badge}
                          </span>
                        )}
                      </div>
                      <span className={`text-[11px] ${isDayMode ? 'text-gray-500' : 'text-[#6a6a6f]'}`}>{model.description}</span>
                    </div>
                    {selected.id === model.id && <Check className="size-4 text-blue-400 flex-shrink-0" />}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AnalysisModeSelector({ selectedMode, onModeChange, isDayMode }) {
  const [isOpen, setIsOpen] = useState(false)
  const selected = analysisModes.find(m => m.id === selectedMode) || analysisModes[0]
  const IconComponent = selected.icon

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all duration-200 ${
          isDayMode
            ? 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
            : 'text-[#8a8a8f] hover:text-white hover:bg-white/5'
        }`}
      >
        <BookOpen className="size-3.5" />
        <span>{selected.name}</span>
        <ChevronDown className={`size-3.5 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className={`absolute bottom-full left-0 mb-2 z-50 min-w-[240px] backdrop-blur-xl border rounded-xl shadow-2xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200 ${
            isDayMode
              ? 'bg-white/95 border-gray-200 shadow-gray-200/50'
              : 'bg-[#1a1a1e]/95 border-white/10 shadow-black/50'
          }`}>
            <div className="p-1.5">
              <div className={`px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider ${
                isDayMode ? 'text-gray-500' : 'text-[#5a5a5f]'
              }`}>
                Analysis Mode
              </div>
              {analysisModes.map((mode) => {
                const ModeIcon = mode.icon
                return (
                  <button
                    key={mode.id}
                    onClick={() => {
                      onModeChange?.(mode.id)
                      setIsOpen(false)
                    }}
                    className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-left transition-all duration-150 ${
                      selected.id === mode.id
                        ? isDayMode ? 'bg-gray-100 text-gray-900' : 'bg-white/10 text-white'
                        : isDayMode ? 'text-gray-600 hover:bg-gray-50 hover:text-gray-900' : 'text-[#a0a0a5] hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    <div className="flex-shrink-0"><ModeIcon className={`size-4 ${mode.iconColor}`} /></div>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium">{mode.name}</span>
                      <span className={`text-[11px] block ${isDayMode ? 'text-gray-500' : 'text-[#6a6a6f]'}`}>{mode.description}</span>
                    </div>
                    {selected.id === mode.id && <Check className="size-4 text-blue-400 flex-shrink-0" />}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export function BoltStyleChatInput({ onSend, onImport, onModelChange, onModeChange, selectedModel, selectedMode, isDayMode }) {
  const [message, setMessage] = useState('')
  const [showAttachMenu, setShowAttachMenu] = useState(false)
  const textareaRef = useRef(null)

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    }
  }, [message])

  const handleSubmit = useCallback(() => {
    if (message.trim()) {
      onSend?.(message, 'hybrid', selectedMode || 'standard')
      setMessage('')
    }
  }, [message, onSend, selectedMode])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }, [handleSubmit])

  const fileInputRef = useRef(null)
  const handleFileClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (file) {
      await uploadFile(file, 'default', null)
      setMessage(prev => prev ? `${prev} (uploaded: ${file.name})` : `Analyze ${file.name}`)
    }
    e.target.value = ''
  }, [])

  return (
    <div className="relative w-full max-w-[680px] mx-auto">
      <div className={`absolute -inset-[1px] rounded-2xl bg-gradient-to-b pointer-events-none ${
        isDayMode ? 'from-gray-300/[0.2] to-transparent' : 'from-white/[0.08] to-transparent'
      }`} />
      <div className={`relative rounded-2xl ring-1 shadow-lg ${
        isDayMode
          ? 'bg-white ring-gray-200 shadow-gray-200/50'
          : 'bg-[#1e1e22] ring-white/[0.08] shadow-[0_0_0_1px_rgba(255,255,255,0.05),0_2px_20px_rgba(0,0,0,0.4)]'
      }`}>
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="What do you want to build?"
            className={`w-full resize-none bg-transparent text-[15px] px-5 pt-5 pb-3 focus:outline-none min-h-[80px] max-h-[200px] ${
              isDayMode ? 'text-gray-900 placeholder-gray-400' : 'text-white placeholder-[#5a5a5f]'
            }`}
            style={{ height: '80px' }}
          />
        </div>

        <div className="flex items-center justify-between px-3 pb-3 pt-1">
          <div className="flex items-center gap-1">
            <div className="relative">
              <button
                onClick={() => setShowAttachMenu(!showAttachMenu)}
                className={`flex items-center justify-center size-8 rounded-full transition-all duration-200 active:scale-95 ${
                  isDayMode
                    ? 'bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700'
                    : 'bg-white/[0.08] hover:bg-white/[0.12] text-[#8a8a8f] hover:text-white'
                }`}
              >
                <Plus className={`size-4 transition-transform duration-200 ${showAttachMenu ? 'rotate-45' : ''}`} />
              </button>

              {showAttachMenu && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setShowAttachMenu(false)} />
                  <div className={`absolute bottom-full left-0 mb-2 z-50 backdrop-blur-xl border rounded-xl shadow-2xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200 ${
                    isDayMode
                      ? 'bg-white/95 border-gray-200 shadow-gray-200/50'
                      : 'bg-[#1a1a1e]/95 border-white/10 shadow-black/50'
                  }`}>
                    <div className="p-1.5 min-w-[180px]">
                      {[
                        { icon: Paperclip, label: 'Upload file', action: handleFileClick },
                        { icon: Globe, label: 'Add URL' },
                        { icon: FileCode, label: 'Import code' }
                      ].map((item, i) => (
                        <button
                          key={i}
                          onClick={item.action}
                          className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all duration-150 ${
                            isDayMode
                              ? 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                              : 'text-[#a0a0a5] hover:bg-white/5 hover:text-white'
                          }`}
                        >
                          <item.icon className="size-4" />
                          <span className="text-sm">{item.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={handleFileChange}
            />
            <ModelSelector selectedModel={selectedModel} onModelChange={onModelChange} isDayMode={isDayMode} />
            <AnalysisModeSelector selectedMode={selectedMode} onModeChange={onModeChange} isDayMode={isDayMode} />
          </div>

          <div className="flex-1" />

          <div className="flex items-center gap-2">
            <button className={`flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium transition-all duration-200 ${
              isDayMode
                ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                : 'text-[#6a6a6f] hover:text-white hover:bg-white/5'
            }`}>
              <Lightbulb className="size-4" />
              <span className="hidden sm:inline">Plan</span>
            </button>

            <button
              onClick={handleSubmit}
              disabled={!message.trim()}
              className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed active:scale-95 shadow-lg ${
                isDayMode
                  ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-blue-600/30'
                  : 'bg-[#1488fc] hover:bg-[#1a94ff] text-white shadow-[0_0_20px_rgba(20,136,252,0.3)]'
              }`}
            >
              <span className="hidden sm:inline">Build now</span>
              <SendHorizontal className="size-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function RayBackground({ isDayMode }) {
  if (isDayMode) {
    return (
      <div className="absolute inset-0 w-full h-full overflow-hidden pointer-events-none select-none">
        <div className="absolute inset-0 bg-gradient-to-b from-gray-50 via-white to-white" />
        <div
          className="absolute top-[-200px] left-1/2 -translate-x-1/2 w-[2000px] h-[1000px] opacity-30"
          style={{
            background: 'radial-gradient(ellipse at center, rgba(59, 130, 246, 0.15) 0%, transparent 60%)'
          }}
        />
        <div
          className="absolute top-[100px] left-[20%] w-[600px] h-[600px] opacity-20 blur-3xl"
          style={{
            background: 'radial-gradient(circle, rgba(147, 51, 234, 0.3) 0%, transparent 70%)'
          }}
        />
        <div
          className="absolute top-[200px] right-[20%] w-[500px] h-[500px] opacity-20 blur-3xl"
          style={{
            background: 'radial-gradient(circle, rgba(59, 130, 246, 0.3) 0%, transparent 70%)'
          }}
        />
      </div>
    )
  }

  return (
    <div className="absolute inset-0 w-full h-full overflow-hidden pointer-events-none select-none">
      <div className="absolute inset-0 bg-[#0f0f0f]" />
      <div
        className="absolute left-1/2 -translate-x-1/2 w-[4000px] h-[1800px] sm:w-[6000px]"
        style={{
          background: `radial-gradient(circle at center 800px, rgba(20, 136, 252, 0.8) 0%, rgba(20, 136, 252, 0.35) 14%, rgba(20, 136, 252, 0.18) 18%, rgba(20, 136, 252, 0.08) 22%, rgba(17, 17, 20, 0.2) 25%)`
        }}
      />
      <div
        className="absolute top-[175px] left-1/2 w-[1600px] h-[1600px] sm:top-1/2 sm:w-[3043px] sm:h-[2865px]"
        style={{ transform: 'translate(-50%) rotate(180deg)' }}
      >
        <div className="absolute w-full h-full rounded-full -mt-[13px]" style={{ background: 'radial-gradient(43.89% 25.74% at 50.02% 97.24%, #111114 0%, #0f0f0f 100%)', border: '16px solid white', transform: 'rotate(180deg)', zIndex: 5 }} />
        <div className="absolute w-full h-full rounded-full bg-[#0f0f0f] -mt-[11px]" style={{ border: '23px solid #b7d7f6', transform: 'rotate(180deg)', zIndex: 4 }} />
        <div className="absolute w-full h-full rounded-full bg-[#0f0f0f] -mt-[8px]" style={{ border: '23px solid #8fc1f2', transform: 'rotate(180deg)', zIndex: 3 }} />
        <div className="absolute w-full h-full rounded-full bg-[#0f0f0f] -mt-[4px]" style={{ border: '23px solid #64acf6', transform: 'rotate(180deg)', zIndex: 2 }} />
        <div className="absolute w-full h-full rounded-full bg-[#0f0f0f]" style={{ border: '20px solid #1172e2', boxShadow: '0 -15px 24.8px rgba(17, 114, 226, 0.6)', transform: 'rotate(180deg)', zIndex: 1 }} />
      </div>
    </div>
  )
}

export function AnnouncementBadge({ text, href = "#", isDayMode }) {
  const content = (
    <>
      <span className="absolute top-0 left-0 right-0 h-1/2 pointer-events-none opacity-70 mix-blend-overlay" style={{ background: 'radial-gradient(ellipse at center, rgba(255, 255, 255, 0.15) 0%, transparent 70%)' }} />
      <span className="absolute -top-px left-1/2 -translate-x-1/2 h-[2px] w-[100px] opacity-60" style={{ background: 'linear-gradient(90deg, transparent 0%, rgba(37, 119, 255, 0.8) 20%, rgba(126, 93, 225, 0.8) 50%, rgba(59, 130, 246, 0.8) 80%, transparent 100%)', filter: 'blur(0.5px)' }} />
      <Bolt className="size-4 relative z-10 text-white" />
      <span className="relative z-10 text-white font-medium">{text}</span>
    </>
  )

  const className = "relative inline-flex items-center gap-2 px-5 py-2 min-h-[40px] rounded-full text-sm overflow-hidden transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
  const style = {
    background: 'linear-gradient(135deg, rgba(255,255,255,0.1), rgba(255,255,255,0.05))',
    backdropFilter: 'blur(20px) saturate(140%)',
    boxShadow: 'inset 0 1px rgba(255,255,255,0.2), inset 0 -1px rgba(0,0,0,0.1), 0 8px 32px -8px rgba(0,0,0,0.1), 0 0 0 1px rgba(255,255,255,0.08)'
  }

  return href !== '#' ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className} style={style}>{content}</a>
  ) : (
    <button className={className} style={style}>{content}</button>
  )
}

export function ImportButtons({ onImport, isDayMode }) {
  return (
    <div className="flex items-center gap-4 justify-center">
      <span className={`text-sm ${isDayMode ? 'text-gray-500' : 'text-[#6a6a6f]'}`}>or import from</span>
      <div className="flex gap-2">
        {[
          { id: 'figma', name: 'Figma', icon: <svg className="size-4" viewBox="0 0 24 24" fill="none"><path d="M8 24C10.208 24 12 22.208 12 20V16H8C5.792 16 4 17.792 4 20C4 22.208 5.792 24 8 24Z" fill="currentColor"/><path d="M4 12C4 9.792 5.792 8 8 8H12V16H8C5.792 16 4 14.208 4 12Z" fill="currentColor"/><path d="M4 4C4 1.792 5.792 0 8 0H12V8H8C5.792 8 4 6.208 4 4Z" fill="currentColor"/><path d="M12 0H16C18.208 0 20 1.792 20 4C20 6.208 18.208 8 16 8H12V0Z" fill="currentColor"/><path d="M20 12C20 14.208 18.208 16 16 16C13.792 16 12 14.208 12 12C12 9.792 13.792 8 16 8C18.208 8 20 9.792 20 12Z" fill="currentColor"/></svg> },
          { id: 'github', name: 'GitHub', icon: <Github className="size-4" /> }
        ].map((option) => (
          <button
            key={option.id}
            onClick={() => onImport?.(option.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all duration-200 active:scale-95 ${
              isDayMode
                ? 'border-gray-200 bg-white hover:bg-gray-50 text-gray-600'
                : 'border-white/10 bg-[#0f0f0f] hover:bg-[#1a1a1e] text-[#8a8a8f] hover:text-white'
            }`}
          >
            {option.icon}
            <span>{option.name}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export function BoltStyleChat({ onSend, onImport, onModelChange, onModeChange, selectedModel, selectedMode }) {
  const { isDayMode } = useBlaiqWorkspace()

  return (
    <div className={`relative flex flex-col items-center justify-center min-h-screen w-full overflow-hidden ${
      isDayMode ? 'bg-white' : 'bg-[#0f0f0f]'
    }`}>
      <RayBackground isDayMode={isDayMode} />

      <div className="absolute top-[55%] left-1/2 sm:top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center justify-center w-full h-full overflow-hidden px-4 z-10">
        <div className="text-center mb-8">
          <h1 className={`text-4xl sm:text-5xl font-bold tracking-tight mb-1 ${
            isDayMode ? 'text-gray-900' : 'text-white'
          }`}>
            What will you{' '}
            <span className={`bg-gradient-to-b bg-clip-text text-transparent italic ${
              isDayMode
                ? 'from-blue-600 via-blue-600 to-blue-400'
                : 'from-[#4da5fc] via-[#4da5fc] to-white'
            }`}>
              build
            </span>
            {' '}today?
          </h1>
          <p className={`text-base font-semibold sm:text-lg ${
            isDayMode ? 'text-gray-500' : 'text-[#8a8a8f]'
          }`}>
            Create stunning reports, pitch decks & analysis by chatting with AI.
          </p>
        </div>

        <div className="w-full max-w-[700px] mb-6 sm:mb-8 mt-4">
          <BoltStyleChatInput
            placeholder="What do you want to build?"
            onSend={onSend}
            onImport={onImport}
            onModelChange={onModelChange}
            onModeChange={onModeChange}
            selectedModel={selectedModel}
            selectedMode={selectedMode}
            isDayMode={isDayMode}
          />
        </div>

        <ImportButtons onImport={onImport} isDayMode={isDayMode} />
      </div>
    </div>
  )
}
