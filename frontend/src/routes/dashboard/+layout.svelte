<script lang="ts">
	import { Toaster } from '$lib/components/ui/sonner/index.js';
	import { ModeWatcher } from 'mode-watcher';
	import AppSidebar from '$lib/components/app-sidebar.svelte';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';

	let { children } = $props();
</script>

<ModeWatcher />
<Toaster />
<Sidebar.Provider>
	<AppSidebar />
	<main class='w-full'>
		{@render children?.()}
	</main>
</Sidebar.Provider>
