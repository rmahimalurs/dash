export default function UnderMaintenance({ message }: { message?: string }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 dark:bg-gray-900 px-6 text-center">
      <img
        src="/chai.gif"
        alt="chai"
        className="w-56 rounded-2xl shadow-lg mb-8 select-none"
        draggable={false}
      />
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
        {message || 'Under Maintenance - Go have a chai'}
      </h1>
      <p className="text-sm ds-u-color--muted mt-3">
        We&apos;ll be back shortly.
      </p>
      <a
        href="/login"
        className="mt-8 text-xs ds-u-color--muted hover:text-gray-600 dark:hover:text-gray-300 underline"
      >
        Admin sign in
      </a>
    </div>
  )
}
