<script lang="ts">
	import { Separator } from '$lib/components/ui/separator';
	import CircleQuestionMark from '@lucide/svelte/icons/circle-question-mark';
	import SearchIcon from '@lucide/svelte/icons/search';
	import type { PageProps } from './$types';
	import * as InputGroup from '$lib/components/ui/input-group';
	import Checkbox from '$lib/components/ui/checkbox/checkbox.svelte';
	import { FetchProtocols, DeleteProtocol, type Protocol } from '$lib/api/protocols';
	import DeleteDialog from '$lib/components/complex/DeleteDialog.svelte';
	import Pagination from '$lib/components/complex/Pagination.svelte';
	import CreateDialog from './CreateDialog.svelte';
	import { COOKIE_MAX_AGE, PAGINATION_LIMITS, PROTOCOLS_LIMIT_COOKIE } from '$lib/constants';

	let { data }: PageProps = $props();
	let list_items = $derived<Protocol[]>(data.protocols);

	let delete_ids = $state<number[]>([]);
	let all_selected = $derived(
		list_items.length > 0 && list_items.every((item) => delete_ids.includes(item.proto_id))
	);

	function selectAll() {
		if (all_selected) {
			delete_ids = [];
		} else {
			delete_ids = list_items.map((item) => item.proto_id);
		}
	}

	function select(id: number) {
		if (!delete_ids.includes(id)) {
			delete_ids = [...delete_ids, id];
		} else {
			delete_ids = delete_ids.filter((i) => i !== id);
		}
	}

	let search_query = $state('');
	let pagination_limit = $derived(data.limit);
	// Persist the chosen page size so it survives reloads (read back by the
	// server load via the cookie for the initial fetch).
	$effect(() => {
		document.cookie = `${PROTOCOLS_LIMIT_COOKIE}=${pagination_limit}; path=/; max-age=${COOKIE_MAX_AGE}`;
	});

	let page_index = $state(0);

	let has_prev = $derived(page_index > 0);
	let has_next = $derived(list_items.length === pagination_limit);

	async function loadPage(index: number) {
		let offset = pagination_limit * index;
		list_items = await FetchProtocols(undefined, pagination_limit, offset);
		page_index = index;
		delete_ids = [];
	}

	async function nextPage() {
		if (!has_next) return;
		await loadPage(page_index + 1);
	}

	async function prevPage() {
		if (!has_prev) return;
		await loadPage(page_index - 1);
	}

	async function resetPagination() {
        await loadPage(0);
    }

	async function refresh() {
		await loadPage(page_index);
	}
</script>

<section class="relative min-h-screen flex flex-col">
	<div class="flex justify-between p-4">
		<div>
			<div class="flex items-center gap-2">
				<h1 class="text-3xl">Protocols</h1>
				<a href="TODO: docs" class="text-primary">
					<CircleQuestionMark size={20} />
				</a>
			</div>
			<p class="opacity-50">Manage your protocols</p>
		</div>
		<CreateDialog onCreated={refresh} />
	</div>
	<Separator />
	<div class="p-4 flex flex-col justify-between gap-4 flex-1">
		<div class="p-4 flex flex-col justify-between gap-4">
			<div class="flex items-center gap-2 max-w-1/3">
				<InputGroup.Root>
					<InputGroup.Input bind:value={search_query} placeholder="Search..." />
					<InputGroup.Addon>
						<SearchIcon />
					</InputGroup.Addon>
				</InputGroup.Root>
			</div>
			<div class="flex items-center gap-2 ml-4">
				<Checkbox checked={all_selected} onCheckedChange={selectAll} /> Select all
			</div>
			<div class="flex flex-col gap-2">
				{#each list_items as ptcl}
					<div class="flex justify-between rounded-md px-4 p-2 border-1 border-border">
						<div>
							<div class="flex items-center gap-2">
								<Checkbox
									checked={delete_ids.includes(ptcl.proto_id)}
									onCheckedChange={() => select(ptcl.proto_id)}
								/>
								<p class="text-lg">{ptcl.name}</p>
								<p class="opacity-50">ID: {ptcl.proto_id}, Template: {ptcl.tmp_name}</p>
							</div>
						</div>
						<!-- <UpdateDialog {template} onUpdated={refresh} /> -->
					</div>
				{/each}
			</div>
		</div>
	</div>
	<Pagination
		limits={PAGINATION_LIMITS}
		bind:limit={pagination_limit}
		hasOrder={false}
		page={page_index}
		hasPrev={has_prev}
		hasNext={has_next}
		onPrev={prevPage}
		onNext={nextPage}
		onReset={resetPagination}
	/>
	<DeleteDialog bind:deleteIds={delete_ids} deleteHook={DeleteProtocol} onDeleted={refresh} />
</section>
