import { cn } from '@/utils/cn'

export default function LoadingSpinner({ className, fullscreen = false }) {
  const spinner = (
    <div className={cn(
      'animate-spin rounded-full border-2 border-slate-300 dark:border-gray-700 border-t-blue-500',
      'h-8 w-8',
      className
    )} />
  )
  if (fullscreen) return (
    <div className="flex items-center justify-center min-h-screen bg-slate-100 dark:bg-gray-950">
      {spinner}
    </div>
  )
  return spinner
}
