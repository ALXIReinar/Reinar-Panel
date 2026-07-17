<script lang="ts">
	import { DeleteTemplate, FetchTemplates, Template } from '$lib/api/templates';
	import DeleteDialog from '$lib/components/complex/DeleteDialog.svelte';
	import Checkbox from '$lib/components/ui/checkbox/checkbox.svelte';
	import * as InputGroup from '$lib/components/ui/input-group';
	import Separator from '$lib/components/ui/separator/separator.svelte';
	import { COOKIE_MAX_AGE, PAGINATION_LIMITS, TEMPLATES_LIMIT_COOKIE } from '$lib/constants';
	import CircleQuestionMark from '@lucide/svelte/icons/circle-question-mark';
	import SearchIcon from '@lucide/svelte/icons/search';
	import type { PageProps } from './$types';
	import CreateDialog from './CreateDialog.svelte';
	import Pagination from '$lib/components/complex/Pagination.svelte';
	import UpdateDialog from './UpdateDialog.svelte';

	let { data }: PageProps = $props();
	// TODO: list virtualisation???
	let list_items = $derived<Template[]>(data.templates);

	let delete_ids = $state<number[]>([]);
	let all_selected = $derived(
		list_items.length > 0 && list_items.every((item) => delete_ids.includes(item.id))
	);

	function selectAll() {
		if (all_selected) {
			delete_ids = [];
		} else {
			delete_ids = list_items.map((item) => item.id);
		}
	}

	function select(id: number) {
		if (!delete_ids.includes(id)) {
			delete_ids = [...delete_ids, id];
		} else {
			delete_ids = delete_ids.filter((i) => i !== id);
		}
	}

	// TODO: search is not implemented in the API right now
	let search_query = $state('');
	let pagination_limit = $derived(data.limit);
	let order_asc = $state(false);

	// Persist the chosen page size so it survives reloads (read back by the
	// server load via the cookie for the initial fetch).
	$effect(() => {
		document.cookie = `${TEMPLATES_LIMIT_COOKIE}=${pagination_limit}; path=/; max-age=${COOKIE_MAX_AGE}`;
	});

	// --- Cursor pagination ---
	// The API has no total count and no page numbers: it takes a `last_id` cursor
	// and returns up to `limit` items. To support "Previous" we keep a stack of the
	// cursors used for each page. cursors[i] is the `last_id` sent to fetch page i
	// (undefined for the first page).
	let cursors = $state<(number | undefined)[]>([undefined]);
	let page_index = $state(0);

	let has_prev = $derived(page_index > 0);
	let has_next = $derived(list_items.length === pagination_limit);

	async function loadPage(index: number) {
		// TODO: search. not implemented at api right now
		list_items = await FetchTemplates(order_asc, pagination_limit, cursors[index]);
		page_index = index;
		delete_ids = [];
	}

	async function nextPage() {
		if (!has_next) return;
		const nextCursor = list_items[list_items.length - 1].id;
		// Drop any forward history and push the cursor for the new page.
		cursors = [...cursors.slice(0, page_index + 1), nextCursor];
		await loadPage(page_index + 1);
	}

	async function prevPage() {
		if (!has_prev) return;
		await loadPage(page_index - 1);
	}

	// Refetch the current page (after create/update/delete).
	async function refresh() {
		await loadPage(page_index);
	}

	// Reset to the first page (when page size or sort order changes).
	async function resetPagination() {
		cursors = [undefined];
		await loadPage(0);
	}
</script>

<section class="relative min-h-screen flex flex-col">
	<div class="flex justify-between p-4">
		<div>
			<div class="flex items-center gap-2">
				<h1 class="text-3xl">Templates</h1>
				<a href="TODO: docs" class="text-primary">
					<CircleQuestionMark size={20} />
				</a>
			</div>
			<p class="opacity-50">Manage your templates</p>
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
				{#each list_items as template}
					<div class="flex justify-between rounded-md px-4 p-2 border-1 border-border">
						<div>
							<div class="flex items-center gap-2">
								<Checkbox
									checked={delete_ids.includes(template.id)}
									onCheckedChange={() => select(template.id)}
								/>
								<p class="text-lg">{template.title}</p>
								<p class="opacity-50">ID: {template.id}, {template.statusString()}</p>
							</div>
							<p class="opacity-80">{template.url_tmp}</p>
						</div>
						<UpdateDialog {template} onUpdated={refresh} />
					</div>
				{/each}
			</div>
		</div>

		<Pagination
			limits={PAGINATION_LIMITS}
			bind:limit={pagination_limit}
            hasOrder={true}
			bind:orderAsc={order_asc}
			page={page_index}
			hasPrev={has_prev}
			hasNext={has_next}
			onPrev={prevPage}
			onNext={nextPage}
			onReset={resetPagination}
		/>
	</div>
	<DeleteDialog bind:deleteIds={delete_ids} deleteHook={DeleteTemplate} onDeleted={refresh} />
</section>
