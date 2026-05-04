import { cn } from '@/utils/cn'

const styles = {
  active:   'bg-green-500/15 text-green-600 dark:text-green-400 border-green-500/30',
  paused:   'bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border-yellow-500/30',
  disabled: 'bg-slate-500/15 dark:bg-gray-500/15 text-slate-600 dark:text-gray-400 border-slate-500/30 dark:border-gray-500/30',
}

export default function BotStatusBadge({ status }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
      styles[status] || styles.disabled
    )}>
      <span className={cn(
        'h-1.5 w-1.5 rounded-full',
        status === 'active' ? 'bg-green-400 animate-pulse' :
        status === 'paused' ? 'bg-yellow-400' : 'bg-slate-400 dark:bg-gray-400'
      )} />
      {status}
    </span>
  )
}
